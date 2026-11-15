Include %occStatus

/// Explicit private opt-in; no HTTP route and no automatic installation/startup.
/// Compile in %SYS only after reviewing exact source and target ownership.
/// Base NativeInstall creates the disabled accounts/databases separately. This
/// helper adds zero security accounts, security roles, privileges or mappings.
Class Chronos.Deployment.NativeWorkflowApply Extends %RegisteredObject
{
ClassMethod NamespaceApply(spec As %DynamicObject, scope As %DynamicObject) As %Status [ Private ]
{
    New $Namespace
    Set $Namespace=spec.namespace
    // No calls to our %SYS helper routines while in the application namespace.
    Set sc=##class(Ens.Director).GetProductionStatus(.name,.state,0) If $$$ISERR(sc) Return sc
    If (state'=2)||((name'="")&&(name'="Chronos.App.Production")) Return $$$ERROR($$$GeneralError,"PRODUCTION_STATE_CHANGED")
    If ##class(EnsLib.Workflow.RoleDefinition).%ExistsId("Chronos.Clarifiers")||##class(EnsLib.Workflow.UserDefinition).%ExistsId(scope.operator)||##class(EnsLib.Workflow.RoleMembership).%ExistsId(scope.%Get("workflow_records").%Get("membership_id")) Return $$$ERROR($$$GeneralError,"WORKFLOW_COLLISION_CHANGED")
    Set sc=##class(EnsLib.Workflow.RoleDefinition).CreateRole("Chronos.Clarifiers") If $$$ISERR(sc) Return sc
    Set sc=##class(EnsLib.Workflow.UserDefinition).CreateUser(scope.operator,"Chronos laboratory clarification operator") If $$$ISERR(sc) Return sc
    Set sc=##class(EnsLib.Workflow.RoleDefinition).AddUserToRole("Chronos.Clarifiers",scope.operator,3,"") If $$$ISERR(sc) Return sc
    Set production=##class(Ens.Config.Production).%OpenId("Chronos.App.Production",0,.sc) If $$$ISERR(sc) Return sc
    If '$IsObject(production)||(production.Items.Count()'=6)||production.Settings.Count() Return $$$ERROR($$$GeneralError,"PRODUCTION_CHANGED_BEFORE_SAVE")
    // Recheck every retained baseline item immediately before changing the OREF.
    For i=1:1:6 {
        Set item=production.Items.GetAt(i),want=scope.%Get("expected_before_items").%Get(i-1)
        If (item.Name'=want.name)||(item.ClassName'=want.%Get("class_name"))||(item.PoolSize'=want.%Get("pool_size"))||(item.Enabled'=want.enabled)||(item.Foreground'=want.foreground)||item.Settings.Count() Return $$$ERROR($$$GeneralError,"BASE_ITEM_CHANGED_BEFORE_SAVE")
    }
    // Insert exactly the five additional items in the fixed reviewed order.
    For i=6:1:10 {
        Set want=scope.%Get("expected_after_items").%Get(i),item=##class(Ens.Config.Item).%New()
        Set item.Name=want.name,item.ClassName=want.%Get("class_name"),item.PoolSize=want.%Get("pool_size"),item.Enabled=1,item.Foreground=0
        For j=0:1:(want.settings.%Size()-1) {
            Set ws=want.settings.%Get(j),setting=##class(Ens.Config.Setting).%New()
            Set setting.Target=ws.target,setting.Name=ws.name,setting.Value=ws.value
            Do item.Settings.Insert(setting)
        }
        Do production.Items.Insert(item)
    }
    Set sc=##class(Ens.Director).GetProductionStatus(.name,.state,0) If $$$ISERR(sc) Return sc
    If (state'=2)||((name'="")&&(name'="Chronos.App.Production")) Return $$$ERROR($$$GeneralError,"PRODUCTION_CHANGED_BEFORE_COMMIT")
    Set sc=production.%Save() If $$$ISERR(sc) Return sc
    // Use the public native writer. The root controller must compare the owned
    // production callback exports before/after; this code does not claim that
    // source equivalence or an atomic cross-class transaction was verified.
    Set sc=production.SaveToClass()
    Set production="",item="",setting=""
    Return sc
}

ClassMethod Apply(scopeJSON As %String, reviewedScopeSHA256 As %String) As %String
{
    Set result={"status":"OPTIN_APPLY_REJECTED","configured":false,"ready":false,"workerAuthorityVerified":false,"modelCalls":0},begun=0
    If '##class(Chronos.Deployment.NativeWorkflowInspect).Context() Return result.%ToJSON()
    Set normalized=##class(Chronos.Deployment.NativeWorkflowInspect).Validate(scopeJSON)
    If normalized="" Return result.%ToJSON()
    Set digest=##class(Chronos.Deployment.NativeWorkflowInspect).Digest(normalized)
    If (reviewedScopeSHA256'=digest) Return result.%ToJSON()
    Set scope=##class(%DynamicObject).%FromJSON(normalized),id=scope.%Get("deployment_id")
    If $System.Util.GetEnviron("CHRONOS_WORKFLOW_OPTIN_APPROVED")'=(id_":"_digest) Return result.%ToJSON()
    Lock +^ChronosInstallLock:0 If '$Test Set result.status="OPTIN_INSTALL_BUSY" Return result.%ToJSON()
    Try {
        Set sc=##class(Chronos.Deployment.NativeWorkflowInspect).Check(scope,0,.before) $$$ThrowOnError(sc)
        If before.status'="OPTIN_PREFLIGHT_CLEAR" Throw ##class(%Exception.General).%New("OPTIN_PREFLIGHT_CHANGED")
        Set spec=##class(Chronos.Deployment.NativeInstall).Spec(id,scope.origin,scope.application)
        // Write-once intent. Any partial attempt blocks a second application;
        // no automatic rollback, deletion, reactivation or blind retry exists.
        Set ^ChronosInstall(id,"workflowOptIn","state")="APPLYING",begun=1
        Set ^ChronosInstall(id,"workflowOptIn","scope")=digest
        Set ^ChronosInstall(id,"workflowOptIn","before")=before.%ToJSON()
        Set ^ChronosInstall(id,"workflowOptIn","phase")="WORKFLOW_RECORDS_AND_PRODUCTION"
        Set sc=..NamespaceApply(spec,scope) $$$ThrowOnError(sc)
        Set ^ChronosInstall(id,"workflowOptIn","state")="VERIFYING_DISABLED"
        Set ^ChronosInstall(id,"workflowOptIn","phase")="READBACK"
        Set sc=##class(Chronos.Deployment.NativeWorkflowInspect).Check(scope,1,.after) $$$ThrowOnError(sc)
        If after.status'="OPTIN_APPLIED_DISABLED_READBACK" Throw ##class(%Exception.General).%New("OPTIN_READBACK_FAILED")
        Set ^ChronosInstall(id,"workflowOptIn","after")=after.%ToJSON()
        Set ^ChronosInstall(id,"workflowOptIn","state")="APPLIED_DISABLED"
        Set ^ChronosInstall(id,"workflowOptIn","phase")="COMPLETE_DISABLED"
        Set result={"status":"OPTIN_APPLIED_DISABLED","configured":true,"ready":false,"accountsAndRouteDisabled":true,"workerAuthorityVerified":false,"taskLifecycleTested":false,"sourceMatched":true,"scopeSha256":(digest),"productionItems":11,"workflowBusinessRecords":3,"securityAccountsAdded":0,"securityRolesAdded":0,"securityGrantsAdded":0,"modelCalls":0}
    } Catch ex {
        If begun Set ^ChronosInstall(id,"workflowOptIn","state")="PARTIAL_PRESERVED_NO_RETRY"
        Set result={"status":($Select(begun:"OPTIN_PARTIAL_PRESERVED_NO_RETRY",1:"OPTIN_PREFLIGHT_REJECTED")),"configured":false,"ready":false,"workerAuthorityVerified":false,"modelCalls":0}
    }
    Lock -^ChronosInstallLock
    Return result.%ToJSON()
}
}
