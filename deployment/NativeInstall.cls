Include %occStatus

/// Trusted console installer, compiled into %SYS only. No HTTP route.
/// Create fresh owned objects only. Accounts/apps stay disabled; no inference.
/// Use native_install.py to verify the complete source bundle BEFORE this class.
Class Chronos.Deployment.NativeInstall Extends %RegisteredObject
{
ClassMethod Match(pattern As %String, value As %String) As %Boolean [ Private ]
{
    Set m=##class(%Regex.Matcher).%New(pattern),m.Text=value,m.OperationLimit=10000
    Return m.Locate()
}

ClassMethod Spec(id As %String, origin As %String, application As %String) As %DynamicObject
{
    If '..Match("\A[a-f0-9]{32}\z",id) Throw ##class(%Exception.General).%New("INVALID_DEPLOYMENT_ID")
    If ($Length(application)>100)||'..Match("\A/csp/chronos(?:-[a-z0-9-]+)?/\z",application) Throw ##class(%Exception.General).%New("INVALID_APPLICATION")
    If ($Length(origin)>256)||'..Match("\Ahttps?://(?:[a-z0-9.-]+|\[::1\])(?::[1-9][0-9]{0,4})?\z",origin) Throw ##class(%Exception.General).%New("INVALID_ORIGIN")
    Set scheme=$Piece(origin,"://",1),authority=$Piece(origin,"://",2)
    Set host=authority,port=""
    If $Extract(host,1)="[" { Set host=$Piece(authority,"]",1)_"]",port=$Piece(authority,"]:",2) }
    ElseIf authority[":" { Set host=$Piece(authority,":",1),port=$Piece(authority,":",2) }
    If (port'="")&&((port>65535)||(port=$Select(scheme="https":443,1:80))) Throw ##class(%Exception.General).%New("INVALID_PORT")
    If scheme="http",'$ListFind($ListBuild("127.0.0.1","localhost","[::1]"),host) Throw ##class(%Exception.General).%New("TLS_REQUIRED")
    Set short=$Extract(id,1,12),ns="CHRONOS_"_$ZConvert(short,"U"),prefix="Chronos_"_short
    Set root="/durable/chronos/"_id,main=root_"/db/",temp=root_"/temp/"
    Set resource="%DB_"_prefix,secondary="%DB_"_ns_"SECONDARY",access=prefix_"_Access"
    Set temporary=resource_"_TEMP"
    Set s={"layoutVersion":4,"id":(id),"namespace":(ns),"prefix":(prefix),"root":(root),"origin":(origin),"application":(application),"access":(access),"resource":(resource),"tempResource":(temporary),"secondaryResource":(secondary)}
    Set s.databases=[{"name":(ns),"directory":(main),"resource":(resource),"journal":3},{"name":(ns_"_TEMP"),"directory":(temp),"resource":(temporary),"journal":2},{"name":(ns_"SECONDARY"),"directory":(main_$ZConvert(ns,"L")_"secondary/"),"resource":(secondary),"journal":3}]
    Set s.roles=[{"name":(prefix_"_Base"),"resources":(resource_":RW,"_temporary_":RW,%DB_IRISSYS:R,"_access_":U")},{"name":(prefix_"_Read"),"resources":"Chronos_Read:U"},{"name":(prefix_"_Approve"),"resources":"Chronos_Approve:U"},{"name":(prefix_"_Python"),"resources":"%Service_EmbeddedPython:U"}]
    Set base=prefix_"_Base,"_prefix_"_Read"
    Set s.users=[{"name":(prefix_"_Reader"),"roles":(base)},{"name":(prefix_"_Operator"),"roles":(base_","_prefix_"_Approve")}]
    Set s.defaultApplication="/csp/"_$ZConvert(ns,"L"),s.webPath=$Extract(application,1,*-1),s.destinations=root_"/owned-destinations"
    Return s
}

ClassMethod Context() As %Boolean [ Private ]
{
    If ($Namespace'="%SYS")||$TLevel||$Data(%request)||$Data(%session) Return 0
    If $Username'="irisowner" Return 0
    Return $ZVersion["2026.3.0AI (Build 154U)"
}

ClassMethod Lookup(class As %String, name As %String, absentCode As %String) As %String [ Private ]
{
    Set sc=0,found=0
    Try { Set found=$ClassMethod(class,"Exists",name,,.sc) }
    Catch ex { Return "LOOKUP_ERROR" }
    If found,$System.Status.IsOK(sc),$System.Status.GetErrorCodes(sc)="" Return "PRESENT"
    If 'found,$System.Status.IsError(sc),$System.Status.GetErrorCodes(sc)=absentCode Return "ABSENT"
    Return "LOOKUP_ERROR"
}

ClassMethod Add(rows As %DynamicArray, kind As %String, name As %String, class As %String, code As %String) [ Private ]
{
    Set status=..Lookup(class,name,code)
    If status="PRESENT" Set status="CONFLICT"
    Do rows.%Push({"kind":(kind),"name":(name),"status":(status)})
}

ClassMethod Inspect(id As %String, origin As %String, application As %String) As %String
{
    Set result={"status":"PREFLIGHT_REJECTED","applied":false,"ready":false,"rows":[]}
    If '..Context() Return result.%ToJSON()
    Try {
        Set s=..Spec(id,origin,application),result.spec=s,rows=result.rows
        Do ..Add(rows,"namespace",s.namespace,"Config.Namespaces","420")
        For i=0:1:2 { Set d=s.databases.%Get(i) Do ..Add(rows,"database",d.name,"Config.Databases","420") }
        For i=0:1:3 { Set role=s.roles.%Get(i) Do ..Add(rows,"role",role.name,"Security.Roles","883") }
        For i=0:1:1 { Set user=s.users.%Get(i) Do ..Add(rows,"user",user.name,"Security.Users","838") }
        For name=s.resource,s.tempResource,s.secondaryResource,s.access { Do ..Add(rows,"resource",name,"Security.Resources","892") }
        For name="Chronos_Read","Chronos_Approve" {
            Set status=..Lookup("Security.Resources",name,"892")
            If status="PRESENT" {
                Kill p Set sc=##class(Security.Resources).Get(name,.p)
                If $System.Status.IsError(sc)||($Get(p("PublicPermission"))'="")||'$ListFind($ListBuild("Owned Chronos HTTP laboratory","Chronos supervised recovery application"),$Get(p("Description"))) Set status="CONFLICT"
            }
            Do rows.%Push({"kind":"shared_resource","name":(name),"status":(status)})
        }
        For name="%Service_EmbeddedPython","%DB_IRISSYS" {
            Set status=..Lookup("Security.Resources",name,"892")
            If status="ABSENT" Set status="MISSING_REQUIRED"
            Do rows.%Push({"kind":"required_resource","name":(name),"status":(status)})
        }
        For name=s.defaultApplication,s.webPath { Do ..Add(rows,"application",name,"Security.Applications","869") }
        For path=s.root,s.destinations { Do rows.%Push({"kind":"directory","name":(path),"status":($Select(##class(%File).Exists(path):"CONFLICT",1:"ABSENT"))}) }
        For i=0:1:2 { Set path=s.databases.%Get(i).directory Do rows.%Push({"kind":"directory","name":(path),"status":($Select(##class(%File).Exists(path):"CONFLICT",1:"ABSENT"))}) }
        Set bad=0
        For i=0:1:(rows.%Size()-1) { If '$ListFind($ListBuild("ABSENT","PRESENT"),rows.%Get(i).status) Set bad=bad+1 }
        If $Data(^ChronosInstall(id)) Set bad=bad+1
        Set result.conflicts=bad,result.intentExists=+$Data(^ChronosInstall(id))
        If bad=0 Set result.status="NAMES_CLEAR_NOT_AUTHORIZATION"
    } Catch ex { Set result.status="PREFLIGHT_FAILED" }
    Return result.%ToJSON()
}

ClassMethod SameList(actual As %String, expected As %String) As %Boolean [ Private ]
{
    If $Length(actual,",")'=$Length(expected,",") Return 0
    For i=1:1:$Length(actual,",") {
        Set part=$Piece(actual,",",i)
        If (part="")||$Data(seen(part))||'$ListFind($ListFromString(expected),part) Return 0
        Set seen(part)=1
    }
    Return 1
}

ClassMethod Database(d As %DynamicObject) As %Status [ Private ]
{
    If ##class(%File).Exists(d.directory) Return $$$ERROR($$$GeneralError,"DATABASE_PATH_EXISTS")
    If '##class(%File).CreateDirectoryChain(d.directory) Return $$$ERROR($$$GeneralError,"DIRECTORY_CREATE_FAILED")
    Set sc=##class(SYS.Database).CreateDatabase(d.directory,8,8192,0,d.resource,d.journal)
    If $$$ISERR(sc) Return sc
    Set p("Directory")=d.directory,p("MountAtStartup")=1
    Return ##class(Config.Databases).Create(d.name,.p)
}

ClassMethod DisableDefault(s As %DynamicObject, Output outcome As %String) As %Status [ Private ]
{
    Set outcome="DEFAULT_APP_CLOSURE_UNVERIFIED"
    Set status=..Lookup("Security.Applications",s.defaultApplication,"869")
    If status="ABSENT" Set outcome="DEFAULT_APP_ABSENT" Return $$$OK
    If status'="PRESENT" Return $$$ERROR($$$GeneralError,"DEFAULT_APP_LOOKUP_FAILED")
    // An intent alone does not prove ownership after a failed namespace create.
    Kill p Set sc=##class(Config.Namespaces).Get(s.namespace,.p) If $$$ISERR(sc) Return sc
    If ($Get(p("Globals"))'=s.namespace)||($Get(p("Routines"))'=s.namespace)||($Get(p("TempGlobals"))'=(s.namespace_"_TEMP")) Return $$$ERROR($$$GeneralError,"NAMESPACE_OWNERSHIP_UNVERIFIED")
    For i=0:1:1 {
        Set d=s.databases.%Get(i)
        If '$Get(^ChronosInstall(s.id,"createdDatabase",d.name)) Return $$$ERROR($$$GeneralError,"DATABASE_NOT_OWNED")
        Kill p Set sc=##class(Config.Databases).Get(d.name,.p) If $$$ISERR(sc) Return sc
        If $Get(p("Directory"))'=d.directory Return $$$ERROR($$$GeneralError,"DATABASE_DIRECTORY_CHANGED")
        Set db=##class(SYS.Database).%OpenId(d.directory)
        If '$IsObject(db)||(db.ResourceName'=d.resource) Return $$$ERROR($$$GeneralError,"DATABASE_RESOURCE_CHANGED")
    }
    Kill p Set sc=##class(Security.Applications).Get(s.defaultApplication,.p)
    If $$$ISERR(sc) Return sc
    If $ZConvert($Get(p("NameSpace")),"U")'=s.namespace Return $$$ERROR($$$GeneralError,"DEFAULT_APP_WRONG_NAMESPACE")
    Kill p Set p("Enabled")=0
    Set sc=##class(Security.Applications).Modify(s.defaultApplication,.p)
    If $$$ISERR(sc) Return sc
    Kill p Set sc=##class(Security.Applications).Get(s.defaultApplication,.p)
    If $$$ISERR(sc)||p("Enabled") Return $$$ERROR($$$GeneralError,"DEFAULT_APP_NOT_DISABLED")
    Set outcome="DEFAULT_APP_DISABLED"
    Return $$$OK
}

ClassMethod VerifyStorage(s As %DynamicObject) As %Status [ Private ]
{
    Kill p Set sc=##class(Config.Namespaces).Get(s.namespace,.p) If $$$ISERR(sc) Return sc
    If ($Get(p("Globals"))'=s.namespace)||($Get(p("Routines"))'=s.namespace)||($Get(p("TempGlobals"))'=(s.namespace_"_TEMP")) Return $$$ERROR($$$GeneralError,"NAMESPACE_STORAGE_CHANGED")
    For i=0:1:2 {
        Set d=s.databases.%Get(i)
        Kill p Set sc=##class(Config.Databases).Get(d.name,.p) If $$$ISERR(sc) Return sc
        If $Get(p("Directory"))'=d.directory Return $$$ERROR($$$GeneralError,"DATABASE_DIRECTORY_CHANGED")
        Set db=##class(SYS.Database).%OpenId(d.directory)
        If '$IsObject(db)||(db.ResourceName'=d.resource) Return $$$ERROR($$$GeneralError,"DATABASE_RESOURCE_READBACK_FAILED")
        If db.GlobalJournalState'=d.journal Return $$$ERROR($$$GeneralError,"JOURNAL_READBACK_FAILED")
    }
    If ##class(%SYS.Namespace).GetGlobalDest(s.namespace,"ChronosRuntime")'=("^"_s.databases.%Get(0).directory) Return $$$ERROR($$$GeneralError,"MAIN_MAPPING_READBACK_FAILED")
    For mapping="IRIS.Temp","IRIS.Temp.EnsJobStatus","IRIS.TempCSPLang" {
        If ##class(%SYS.Namespace).GetGlobalDest(s.namespace,mapping)'=("^"_s.databases.%Get(1).directory) Return $$$ERROR($$$GeneralError,"TEMP_MAPPING_READBACK_FAILED")
    }
    If ##class(%SYS.Namespace).GetGlobalDest(s.namespace,"Ens.SecondaryData")'=("^"_s.databases.%Get(2).directory) Return $$$ERROR($$$GeneralError,"SECONDARY_MAPPING_READBACK_FAILED")
    For name=s.resource,s.tempResource,s.secondaryResource,s.access,"Chronos_Read","Chronos_Approve" {
        Kill p Set sc=##class(Security.Resources).Get(name,.p) If $$$ISERR(sc) Return sc
        If $Get(p("PublicPermission"))'="" Return $$$ERROR($$$GeneralError,"RESOURCE_PUBLIC_READBACK_FAILED")
    }
    Return $$$OK
}

ClassMethod VerifyDisabled(s As %DynamicObject) As %Status [ Private ]
{
    Set sc=..VerifyStorage(s) If $$$ISERR(sc) Return sc
    For i=0:1:3 {
        Set role=s.roles.%Get(i)
        Kill p Set sc=##class(Security.Roles).Get(role.name,.p) $$$ThrowOnError(sc)
        If '..SameList(p("Resources"),role.resources)||($Get(p("GrantedRoles"))'="")||p("EscalationOnly") Return $$$ERROR($$$GeneralError,"ROLE_READBACK_FAILED")
    }
    For i=0:1:1 {
        Set user=s.users.%Get(i)
        Kill p Set sc=##class(Security.Users).Get(user.name,.p) $$$ThrowOnError(sc)
        If p("Enabled")||'..SameList(p("Roles"),user.roles)||($Get(p("EscalationRoles"))'="") Return $$$ERROR($$$GeneralError,"USER_READBACK_FAILED")
    }
    Kill p Set sc=##class(Security.Applications).Get(s.webPath,.p) $$$ThrowOnError(sc)
    If p("Enabled")||(p("Resource")'=s.access)||(p("AutheEnabled")'=32)||(p("MatchRoles")'=(s.prefix_"_Read:"_s.prefix_"_Python")) Return $$$ERROR($$$GeneralError,"APP_AUTH_READBACK_FAILED")
    If (p("DispatchClass")'="Chronos.Web.API")||(p("EventClass")'="Chronos.Web.Events")||(p("NameSpace")'=s.namespace)||(p("Timeout")'=3600) Return $$$ERROR($$$GeneralError,"APP_READBACK_FAILED")
    If (p("UseCookies")'=2)||(p("CookiePath")'=s.application)||(p("SessionScope")'=2)||(p("UserCookieScope")'=2)||p("GroupById")||'p("CSPZENEnabled") Return $$$ERROR($$$GeneralError,"COOKIE_READBACK_FAILED")
    Return ..DisableDefault(s)
}

ClassMethod EmptyCatalog(root As %String, module As %String) [ Language = python, Private ]
{
    import importlib
    # Module was obtained from the validated namespace-isolated product loader.
    importlib.import_module(module).Runtime(root,create=True)
}

ClassMethod ApplicationPhase(s As %DynamicObject) As %Status [ Private ]
{
    New $Namespace
    Set $Namespace=s.namespace
    Set sc=$System.OBJ.LoadDir("/opt/chronos/src/Chronos","ck",.errors,1)
    If $$$ISERR(sc) Return sc
    Set module=##class(Chronos.Runtime.Python).Module("/opt/chronos/src",$Namespace)
    Set $Namespace="%SYS"
    Do ..EmptyCatalog(s.destinations,module)
    Set $Namespace=s.namespace
    Set sc=##class(Chronos.Runtime.Bootstrap).Configure("Chronos.App.Production",s.destinations,"/opt/chronos/src")
    If $$$ISERR(sc) Return sc
    Set installationId=$ZConvert($System.Encryption.ToHex($System.Encryption.GenCryptRand(32,1)),"L")
    If $Length(installationId)'=64 Return $$$ERROR($$$GeneralError,"INSTALLATION_ID_FAILED")
    If $Data(^ChronosWeb("config")) Return $$$ERROR($$$GeneralError,"WEB_CONFIG_EXISTS")
    Set ^ChronosWeb("config")={"origin":(s.origin),"application":(s.application),"installationId":(installationId)}.%ToJSON()
    Return $$$OK
}

ClassMethod Install(id As %String, origin As %String, application As %String, digest As %String) As %String
{
    Set result={"status":"INSTALL_REJECTED","ready":false,"accountsEnabled":false,"modelCalls":0}
    If '..Context() Return result.%ToJSON()
    If '..Match("\A[a-f0-9]{64}\z",digest) Return result.%ToJSON()
    If $System.Util.GetEnviron("CHRONOS_INSTALL_APPROVED")'=(id_":"_digest) Return result.%ToJSON()
    Lock +^ChronosInstallLock:0
    If '$Test Set result.status="INSTALL_BUSY" Return result.%ToJSON()
    Set begun=0
    Try {
        Set check=##class(%DynamicObject).%FromJSON(..Inspect(id,origin,application))
        If check.status'="NAMES_CLEAR_NOT_AUTHORIZATION" Throw ##class(%Exception.General).%New("PREFLIGHT_CHANGED")
        Set s=check.spec,begun=1
        Set ^ChronosInstall(id,"state")="INSTALLING",^ChronosInstall(id,"spec")=s.%ToJSON(),^ChronosInstall(id,"bundle")=digest
        Set ^ChronosInstall(id,"phase")="RESOURCES"
        For name=s.resource,s.tempResource,s.secondaryResource,s.access,"Chronos_Read","Chronos_Approve" {
            Set status=..Lookup("Security.Resources",name,"892")
            If status="ABSENT" {
                Set sc=##class(Security.Resources).Create(name,"Chronos supervised recovery application","") $$$ThrowOnError(sc)
                Set ^ChronosInstall(id,"createdResource",name)=1
            } Else {
                If (status'="PRESENT")||'$ListFind($ListBuild("Chronos_Read","Chronos_Approve"),name) Throw ##class(%Exception.General).%New("RESOURCE_LOOKUP_OR_COLLISION")
                Kill p Set sc=##class(Security.Resources).Get(name,.p) $$$ThrowOnError(sc)
                If ($Get(p("PublicPermission"))'="")||'$ListFind($ListBuild("Owned Chronos HTTP laboratory","Chronos supervised recovery application"),$Get(p("Description"))) Throw ##class(%Exception.General).%New("SHARED_RESOURCE_CHANGED")
            }
        }
        For name=s.resource,s.tempResource,s.secondaryResource,s.access,"Chronos_Read","Chronos_Approve" {
            Kill p Set sc=##class(Security.Resources).Get(name,.p) $$$ThrowOnError(sc)
            If $Get(p("PublicPermission"))'="" Throw ##class(%Exception.General).%New("RESOURCE_PUBLIC_READBACK_FAILED")
        }
        Set ^ChronosInstall(id,"phase")="DATABASES"
        For i=0:1:1 {
            Set d=s.databases.%Get(i),sc=..Database(d) $$$ThrowOnError(sc)
            Set ^ChronosInstall(id,"createdDatabase",d.name)=1
        }
        Kill p Set p("Globals")=s.namespace,p("Routines")=s.namespace,p("TempGlobals")=s.namespace_"_TEMP",p("Interop")=1
        Set ^ChronosInstall(id,"phase")="NAMESPACE",^ChronosInstall(id,"namespaceIntent")=1
        Set sc=##class(Config.Namespaces).Create(s.namespace,.p)
        // Check/disable the automatically created route even on partial failure.
        Set ^ChronosInstall(id,"namespaceCreateOK")=+$System.Status.IsOK(sc),^ChronosInstall(id,"namespaceCreateCodes")=$System.Status.GetErrorCodes(sc)
        Set disable=..DisableDefault(s,.closure),^ChronosInstall(id,"defaultApplicationClosure")=closure
        $$$ThrowOnError(sc) $$$ThrowOnError(disable)
        Set ^ChronosInstall(id,"phase")="STORAGE_READBACK",^ChronosInstall(id,"namespaceCreated")=1
        // Build154 reuses the explicit private TEMP; SECONDARY is implicit.
        // Reject unexpected mappings/resources instead of repairing them here.
        Set sc=..VerifyStorage(s) $$$ThrowOnError(sc)
        Set ^ChronosInstall(id,"phase")="APPLICATION_CLASSES"
        Set sc=..ApplicationPhase(s) $$$ThrowOnError(sc)
        Set ^ChronosInstall(id,"phase")="ROLES"
        For i=0:1:3 {
            Set role=s.roles.%Get(i)
            Set sc=##class(Security.Roles).Create(role.name,"Chronos scoped application role",role.resources,"",0) $$$ThrowOnError(sc)
        }
        Set ^ChronosInstall(id,"phase")="DISABLED_USERS"
        For i=0:1:1 {
            Set user=s.users.%Get(i),password=$System.Encryption.ToHex($System.Encryption.GenCryptRand(32,1))
            If $Length(password)'=64 Throw ##class(%Exception.General).%New("EPHEMERAL_PASSWORD_FAILED")
            // Enabled=0 at creation, password exists only in this process memory.
            Set sc=##class(Security.Users).Create(user.name,user.roles,password,"Chronos application operator",s.namespace,"","",1,0,"Chronos disabled pending private setup",1,,,.attributes,1,0)
            Set password="" $$$ThrowOnError(sc)
            Set ^ChronosInstall(id,"createdUser",user.name)=1
        }
        Set ^ChronosInstall(id,"phase")="DISABLED_APPLICATION"
        Kill p
        Set p("NameSpace")=s.namespace,p("DispatchClass")="Chronos.Web.API",p("EventClass")="Chronos.Web.Events",p("Enabled")=0
        Set p("AutheEnabled")=32,p("UseCookies")=2,p("CookiePath")=s.application,p("SessionScope")=2,p("UserCookieScope")=2,p("GroupById")=0,p("Timeout")=3600
        Set p("Resource")=s.access,p("MatchRoles")=s.prefix_"_Read:"_s.prefix_"_Python",p("CSPZENEnabled")=1,p("Description")="Chronos supervised recovery application"
        Set sc=##class(Security.Applications).Create(s.webPath,.p) $$$ThrowOnError(sc)
        Set ^ChronosInstall(id,"createdApplication")=1
        Set ^ChronosInstall(id,"phase")="FINAL_READBACK"
        Set sc=..VerifyDisabled(s) $$$ThrowOnError(sc)
        Set ^ChronosInstall(id,"state")="NATIVE_INSTALLED_DISABLED",result.status="NATIVE_INSTALLED_DISABLED",result.spec=s
    } Catch ex {
        Set password=""
        If begun Set ^ChronosInstall(id,"state")="PARTIAL_INSTALL_PRESERVED"
        Set result.status=$Select(begun:"PARTIAL_INSTALL_PRESERVED",1:"PREFLIGHT_REJECTED")
        // No deletion, retry, quota reset or automatic account activation.
        // No exception arguments or details: Create may contain a password.
    }
    Lock -^ChronosInstallLock
    Return result.%ToJSON()
}
}
