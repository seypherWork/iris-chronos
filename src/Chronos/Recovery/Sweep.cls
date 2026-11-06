Include %occStatus

/// Bounded boot recovery, internal trusted controller. No Submit or approval.
/// Caller must install a finite-time provider and keep ingress disabled on boot.
/// Each call processes one durable page; continue until gate.state is OPEN.
Class Chronos.Recovery.Sweep Extends %RegisteredObject
{
Property Coordinator As Chronos.Recovery.Coordinator [ Private ];

Method %OnNew(provider As Chronos.Recovery.Provider) As %Status
{
    Set ..Coordinator=##class(Chronos.Recovery.Coordinator).%New(provider)
    If '$IsObject(..Coordinator) Return $$$ERROR($$$GeneralError,"INVALID_PROVIDER")
    Return $$$OK
}

Method Page(limit As %Integer = 25, Output result As %DynamicObject) As %Status
{
    Set result={"code":"RECOVERY_NOT_FINISHED","dispatchGranted":false}
    If $TLevel Return $$$ERROR($$$GeneralError,"NO_TRANSACTION_DURING_RECOVERY")
    If (limit<1)||(limit>100)||(limit'=(limit\1)) Return $$$ERROR($$$GeneralError,"BAD_BATCH_LIMIT")
    Lock +^ChronosRecovery("sweep"):0
    If '$Test Return $$$ERROR($$$GeneralError,"RECOVERY_WORKER_BUSY")
    Set sc=$$$OK
    Try {
        Set sc=##class(Chronos.Authority.Store).Apply("RECOVERY_STATUS",{},.status)
        $$$ThrowOnError(sc)
        Set runId=status.gate.runId
        If status.gate.state'="RUNNING" Set runId="recovery-"_$System.Util.CreateGUID()
        Set sc=##class(Chronos.Authority.Store).Apply("RECOVERY_BEGIN",{"runId":(runId)},.begun)
        $$$ThrowOnError(sc)
        Set sc=##class(Chronos.Authority.Store).Apply("RECOVERY_BATCH",{"runId":(runId),"limit":(limit)},.batch)
        $$$ThrowOnError(sc)
        Set items=batch.gate.items
        For n=0:1:items.%Size()-1 {
            Set sc=..Coordinator.Reconcile(items.%Get(n),.reconciled)
            $$$ThrowOnError(sc)
        }
        Set sc=##class(Chronos.Authority.Store).Apply("RECOVERY_ACK",{"runId":(runId),"batchId":(batch.gate.batchId)},.result)
        $$$ThrowOnError(sc)
    } Catch ex {
        If $$$ISOK(sc) Set sc=$$$ERROR($$$GeneralError,"RECOVERY_PAGE_FAILED")
        Set result={"code":"RECOVERY_NOT_FINISHED","dispatchGranted":false}
    }
    Lock -^ChronosRecovery("sweep")
    Return sc
}
}
