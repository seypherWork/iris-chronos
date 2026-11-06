Include %occStatus

/// Trusted installation/lifecycle controller. No public configuration endpoint.
/// Call Recover from Ens.Production.OnStart BEFORE hosts/ingress are created.
Class Chronos.Runtime.Bootstrap Extends %RegisteredObject
{
ClassMethod Configure(production As %String, dataRoot As %String, pythonRoot As %String) As %Status
{
    If $TLevel Return $$$ERROR($$$GeneralError,"BOOTSTRAP_REQUIRES_NO_TRANSACTION")
    If $Extract(production,1,8)'="Chronos." Return $$$ERROR($$$GeneralError,"CHRONOS_PRODUCTION_REQUIRED")
    If '##class(%Dictionary.CompiledClass).%ExistsId(production) Return $$$ERROR($$$GeneralError,"PRODUCTION_CLASS_MISSING")
    Set config={"production":(production),"dataRoot":(dataRoot),"pythonRoot":(pythonRoot)}
    Lock +^ChronosRuntime("bootLock"):0
    If '$Test Return $$$ERROR($$$GeneralError,"BOOTSTRAP_BUSY")
    Set sc=$$$OK
    Try {
        Set prior=$Get(^ChronosRuntime("config"))
        If prior'="" {
            If prior'=config.%ToJSON() Set sc=$$$ERROR($$$GeneralError,"BOOTSTRAP_CONFIG_IMMUTABLE")
        } Else {
            Set sc=..CloseGate(.gate)
            $$$ThrowOnError(sc)
            Set candidate=##class(Chronos.Destination.Simulator).%New(dataRoot,pythonRoot)
            If '$IsObject(candidate) Throw ##class(%Exception.General).%New("INVALID_PROVIDER")
            Set ^ChronosRuntime("config")=config.%ToJSON()
            Set ^ChronosRuntime("state")={"state":"CONFIGURED","production":(production),"generation":""}.%ToJSON()
        }
    } Catch ex {
        If $$$ISOK(sc) Set sc=$$$ERROR($$$GeneralError,"BOOTSTRAP_CONFIG_FAILED")
    }
    Lock -^ChronosRuntime("bootLock")
    Return sc
}

ClassMethod CloseGate(Output result As %DynamicObject) As %Status [ Private ]
{
    Set sc=##class(Chronos.Authority.Store).Apply("RECOVERY_STATUS",{},.status)
    If $$$ISERR(sc) Return sc
    Set run=status.gate.runId
    If status.gate.state'="RUNNING" Set run="boot-"_$System.Util.CreateGUID()
    Return ##class(Chronos.Authority.Store).Apply("RECOVERY_BEGIN",{"runId":(run)},.result)
}

ClassMethod Now() As %Numeric [ Private ]
{
    Set stamp=$ZTimestamp
    Return $Piece(stamp,",",1)*86400+$Piece(stamp,",",2)
}

/// Budget checked between pages, not a hard interrupt of an in-progress Query.
ClassMethod Recover(production As %String, started As %String, maxPages As %Integer = 100, maxSeconds As %Integer = 30) As %Status
{
    If $TLevel Return $$$ERROR($$$GeneralError,"BOOTSTRAP_REQUIRES_NO_TRANSACTION")
    If (maxPages<1)||(maxPages>1000)||(maxPages'=(maxPages\1)) Return $$$ERROR($$$GeneralError,"INVALID_PAGE_BUDGET")
    If (maxSeconds<1)||(maxSeconds>300)||(maxSeconds'=(maxSeconds\1)) Return $$$ERROR($$$GeneralError,"INVALID_TIME_BUDGET")
    Lock +^ChronosRuntime("bootLock"):0
    If '$Test Return $$$ERROR($$$GeneralError,"BOOTSTRAP_BUSY")
    Set sc=$$$OK,done=0,generation=$System.Util.CreateGUID()
    Set state={"state":"RECOVERING","production":(production),"started":(started),"generation":(generation),"pages":0}
    Set ^ChronosRuntime("state")=state.%ToJSON()
    Try {
        Set sc=..CloseGate(.gate)
        $$$ThrowOnError(sc)
        Set config=##class(%DynamicObject).%FromJSON($Get(^ChronosRuntime("config")))
        If config.production'=production Throw ##class(%Exception.General).%New("WRONG_PRODUCTION")
        Set sc=..Provider(.provider)
        $$$ThrowOnError(sc)
        Set sweep=##class(Chronos.Recovery.Sweep).%New(provider)
        If '$IsObject(sweep) Throw ##class(%Exception.General).%New("NO_SWEEP")
        Set deadline=..Now()+maxSeconds
        For page=1:1:maxPages {
            If ..Now()'<deadline Quit
            Set sc=sweep.Page(10,.result)
            $$$ThrowOnError(sc)
            Set state.pages=page,^ChronosRuntime("state")=state.%ToJSON()
            If result.gate.state="OPEN" Set done=1 Quit
        }
        If 'done Set sc=$$$ERROR($$$GeneralError,"BOOT_RECOVERY_INCOMPLETE")
        If done Set state.state="RECOVERED"
    } Catch ex {
        If $$$ISOK(sc) Set sc=$$$ERROR($$$GeneralError,"BOOT_RECOVERY_FAILED")
    }
    If $$$ISERR(sc) {
        // BEGIN itself may fail. FAILED still prevents readiness; never pretend
        // that this second best-effort close succeeded without its status.
        Set closeStatus=..CloseGate(.closed)
        Set state.state="FAILED"
        Do state.%Set("gateCloseConfirmed",$$$ISOK(closeStatus),"boolean")
    }
    Set ^ChronosRuntime("state")=state.%ToJSON()
    Lock -^ChronosRuntime("bootLock")
    Return sc
}

ClassMethod Provider(Output provider As Chronos.Destination.Simulator) As %Status
{
    If $TLevel Return $$$ERROR($$$GeneralError,"BOOTSTRAP_REQUIRES_NO_TRANSACTION")
    Try {
        Set config=##class(%DynamicObject).%FromJSON($Get(^ChronosRuntime("config")))
        Set provider=##class(Chronos.Destination.Simulator).%New(config.dataRoot,config.pythonRoot)
        If '$IsObject(provider) Throw ##class(%Exception.General).%New("INVALID_PROVIDER")
    } Catch ex {
        Return $$$ERROR($$$GeneralError,"CONFIGURED_PROVIDER_UNAVAILABLE")
    }
    Return $$$OK
}

/// Only the single documented IRIS runtime-lock error is transient. Composite
/// statuses and unrelated errors remain failures, even if they contain this code.
ClassMethod ProductionBusy(sc As %Status) As %Boolean
{
    Return $System.Status.IsError(sc)&&($System.Status.GetErrorCodes(sc)="<Ens>ErrCanNotAcquireRuntimeLock")
}

/// Ingress must require this check and bind requests to the returned generation.
ClassMethod Ready(Output result As %DynamicObject, expectedGeneration As %String = "") As %Status
{
    Set result={"ready":false,"generation":""}
    If $TLevel Return $$$ERROR($$$GeneralError,"BOOTSTRAP_REQUIRES_NO_TRANSACTION")
    Lock +^ChronosRuntime("bootLock"):0
    If '$Test Return $$$OK
    Set sc=$$$OK
    Try {
        Set sc=..ReadyLocked(.result,expectedGeneration)
    } Catch ex {
        Set sc=$$$ERROR($$$GeneralError,"BOOT_READINESS_UNAVAILABLE")
    }
    Lock -^ChronosRuntime("bootLock")
    Return sc
}

ClassMethod ReadyLocked(Output result As %DynamicObject, expectedGeneration As %String) As %Status [ Private ]
{
    Set result={"ready":false,"generation":""}
    Try {
        Set config=##class(%DynamicObject).%FromJSON($Get(^ChronosRuntime("config")))
        Set state=##class(%DynamicObject).%FromJSON($Get(^ChronosRuntime("state")))
        If (state.state'="RECOVERED")||(state.production'=config.production) Return $$$OK
        If (expectedGeneration'="")&&(expectedGeneration'=state.generation) Return $$$OK
        // StopProduction owns the runtime lock before invoking OnStop. Do not
        // wait on that lock while holding bootLock in the opposite order.
        Set sc=##class(Ens.Director).GetProductionStatus(.name,.productionState,0)
        // Preserve only this typed transient for lifecycle observers. Ingress
        // still receives an error and ready=false; no permission is granted.
        If ..ProductionBusy(sc) Return sc
        $$$ThrowOnError(sc)
        If (name'=config.production)||(productionState'=1) Return $$$OK
        Set sc=##class(Chronos.Authority.Store).Apply("RECOVERY_STATUS",{},.gate)
        $$$ThrowOnError(sc)
        If gate.gate.state'="OPEN" Return $$$OK
        Set result={"ready":true,"generation":(state.generation),"production":(name),"started":(state.started)}
    } Catch ex {
        Return $$$ERROR($$$GeneralError,"BOOT_READINESS_UNAVAILABLE")
    }
    Return $$$OK
}

ClassMethod Stopped(production As %String, stopped As %String, Output result As %DynamicObject) As %Status
{
    Set result={"code":"STOP_IGNORED","closed":false}
    // IRIS 154 passes the STOP time despite naming the callback parameter
    // pTimeStarted. Reject old callbacks and never close a running generation.
    Lock +^ChronosRuntime("bootLock"):5
    If '$Test Set result.code="STOP_GATE_CLOSE_BUSY" Return $$$ERROR($$$GeneralError,"BOOTSTRAP_BUSY")
    Set sc=$$$OK
    Try {
        Set state=##class(%DynamicObject).%FromJSON($Get(^ChronosRuntime("state")))
        Set sc=##class(Ens.Director).GetProductionStatus(.name,.productionState,0)
        $$$ThrowOnError(sc)
        If stopped'?4N1"-"2N1"-"2N1" "2N1":"2N1":"2N1"."3N Throw ##class(%Exception.General).%New("INVALID_STOP_TIME")
        If state.started'?4N1"-"2N1"-"2N1" "2N1":"2N1":"2N1"."3N Throw ##class(%Exception.General).%New("INVALID_START_TIME")
        If (state.production=production)&&(productionState'=1)&&((stopped=state.started)||(stopped]state.started)) {
            Set state.state="STOPPED",state.stopped=stopped,^ChronosRuntime("state")=state.%ToJSON()
            Set sc=..CloseGate(.gate)
            If $$$ISOK(sc) Set result={"code":"STOP_GATE_CLOSED","closed":true}
        }
    } Catch ex {
        Set sc=$$$ERROR($$$GeneralError,"BOOT_STOP_FAILED")
    }
    If $$$ISERR(sc) Set result={"code":"STOP_GATE_CLOSE_FAILED","closed":false}
    Lock -^ChronosRuntime("bootLock")
    Return sc
}

}
