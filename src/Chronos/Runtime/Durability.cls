Include %occStatus

/// Internal durability barrier. No settings, privileges, journal rotation or I/O retry.
/// A logical TCommit alone does not guarantee persistence before external I/O.
Class Chronos.Runtime.Durability Extends %RegisteredObject
{
/// Read only the existing runtime global metadata in the already-resolved local
/// database. No namespace switch, administrative role or cached installation proof.
/// Build154 DirectoryList reports Journal as "Yes"; every other value fails closed.
ClassMethod JournaledStorage(destination As %String) As %Status
{
    Set rows="",sc=$$$OK
    Try {
        If ($Length(destination,"^")'=2)||($Piece(destination,"^",1)'="")||($Piece(destination,"^",2)="") Throw ##class(%Exception.General).%New("LOCAL_STORAGE_REQUIRED")
        Set rows=##class(%ResultSet).%New("%SYS.GlobalQuery:DirectoryList")
        Set sc=rows.Execute($Piece(destination,"^",2),"","ChronosRuntime",0,,1) $$$ThrowOnError(sc)
        Set found=rows.Next(.readStatus) $$$ThrowOnError(readStatus)
        If 'found Throw ##class(%Exception.General).%New("RUNTIME_STORAGE_MISSING")
        If (rows.Get("Name")'="ChronosRuntime")||(rows.Get("Journal")'="Yes") Throw ##class(%Exception.General).%New("JOURNALED_STORAGE_REQUIRED")
        Set extra=rows.Next(.readStatus) $$$ThrowOnError(readStatus)
        If extra Throw ##class(%Exception.General).%New("AMBIGUOUS_STORAGE")
    } Catch ex {
        Set sc=$$$ERROR($$$GeneralError,"JOURNALED_STORAGE_UNVERIFIED")
    }
    Try {
        If $IsObject(rows) {
            Set closeStatus=rows.Close()
            If $$$ISOK(sc),$$$ISERR(closeStatus) Set sc=$$$ERROR($$$GeneralError,"JOURNALED_STORAGE_UNVERIFIED")
        }
    } Catch ex {
        If $$$ISOK(sc) Set sc=$$$ERROR($$$GeneralError,"JOURNALED_STORAGE_UNVERIFIED")
    }
    Return sc
}

ClassMethod Check() As %Status
{
    Try {
        If ##class(%SYS.Journal.System).GetState()'=0 Return $$$ERROR($$$GeneralError,"JOURNAL_NOT_AVAILABLE")
    } Catch ex {
        Return $$$ERROR($$$GeneralError,"JOURNAL_STATE_UNAVAILABLE")
    }
    Return $$$OK
}

/// Caller retains its authority/lifecycle mutex and has ended its transaction.
/// Sync returns an offset, not a %Status. Never expose it as a permission grant.
ClassMethod Flush() As %Status
{
    If $TLevel Return $$$ERROR($$$GeneralError,"DURABILITY_REQUIRES_COMMITTED_TRANSACTION")
    Try {
        Set sc=..Check()
        If $$$ISERR(sc) Return sc
        Set offset=##class(%SYS.Journal.System).Sync()
        If (offset<1)||(offset'=(offset\1)) Return $$$ERROR($$$GeneralError,"JOURNAL_SYNC_NOT_CONFIRMED")
        Set sc=..Check()
        If $$$ISERR(sc) Return sc
    } Catch ex {
        Return $$$ERROR($$$GeneralError,"JOURNAL_SYNC_UNCERTAIN")
    }
    Return $$$OK
}
}
