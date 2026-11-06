Include %occStatus

/// Fixed owned A/B provider. Trusted composition only, not a public endpoint.
/// Python package must be installed by deployment; data root is operator config.
/// No URL, class, path, receipt or authenticated actor is chosen by the agent.
Class Chronos.Destination.Simulator Extends Chronos.Recovery.Provider
{
Property Root As %String [ Private ];
Property Module As %String [ Private ];

Method %OnNew(root As %String, pythonRoot As %String) As %Status
{
    Set ..Root=root
    Try {
        Set ..Module=##class(Chronos.Runtime.Python).Module(pythonRoot,$Namespace)
        Set checked=..Python(root,"VALIDATE","{}",..Module)
    } Catch ex {
        Return $$$ERROR($$$GeneralError,"SIMULATOR_CONFIGURATION_UNAVAILABLE")
    }
    Return $$$OK
}

Method Submit(operation As %DynamicObject, ticket As %DynamicObject, Output receipt As %DynamicObject) As %Status
{
    If $TLevel Return $$$ERROR($$$GeneralError,"NO_TRANSACTION_DURING_PROVIDER_IO")
    Try {
        If 'ticket.%Get("dispatchGranted") Throw ##class(%Exception.General).%New("ADMITTED_TICKET_REQUIRED")
        If (ticket.%Get("code")'="DISPATCH_ADMITTED")||(ticket.%Get("admissionId")="")||(ticket.%Get("admissionId")'=operation.%Get("admissionId"))||(ticket.%Get("admittedAt")'=operation.%Get("admittedAt")) Throw ##class(%Exception.General).%New("ADMISSION_BINDING_REQUIRED")
        If operation.%IsDefined("reviewDeadlineUS")||ticket.%IsDefined("reviewDeadlineUS") {
            If (operation.%GetTypeOf("reviewDeadlineUS")'="number")||(ticket.%GetTypeOf("reviewDeadlineUS")'="number")||(operation.reviewDeadlineUS'=ticket.reviewDeadlineUS) Throw ##class(%Exception.General).%New("HUMAN_DEADLINE_BINDING_REQUIRED")
            If (operation.reviewDeadlineUS<1)||(operation.reviewDeadlineUS'=(operation.reviewDeadlineUS\1)) Throw ##class(%Exception.General).%New("HUMAN_DEADLINE_BINDING_REQUIRED")
            Set deadline=(operation.reviewDeadlineUS/1000000)+($ZDateH("1970-01-01",3)*86400)
            If (operation.validUntil>deadline)||(operation.dispatchAt'<deadline)||(operation.admittedAt'<deadline) Throw ##class(%Exception.General).%New("HUMAN_DEADLINE_BINDING_REQUIRED")
        }
        Set args={"operation":(operation),"ticket":(ticket)}
        Set receipt=##class(%DynamicObject).%FromJSON(..Python(..Root,"SUBMIT",args.%ToJSON(),..Module))
    } Catch ex {
        Return $$$ERROR($$$GeneralError,"SIMULATOR_SUBMIT_UNCERTAIN")
    }
    Return $$$OK
}

Method Query(operation As %DynamicObject, Output receipt As %DynamicObject) As %Status
{
    If $TLevel Return $$$ERROR($$$GeneralError,"NO_TRANSACTION_DURING_PROVIDER_IO")
    Try {
        Set args={"operation":(operation)}
        Set receipt=##class(%DynamicObject).%FromJSON(..Python(..Root,"QUERY",args.%ToJSON(),..Module))
    } Catch ex {
        Return $$$ERROR($$$GeneralError,"SIMULATOR_QUERY_UNCERTAIN")
    }
    Return $$$OK
}

Method Snapshot(orderId As %String, Output snapshot As %DynamicObject) As %Status
{
    If $TLevel Return $$$ERROR($$$GeneralError,"NO_TRANSACTION_DURING_PROVIDER_IO")
    Try {
        Set args={"orderId":(orderId)}
        Set snapshot=##class(%DynamicObject).%FromJSON(..Python(..Root,"SNAPSHOT",args.%ToJSON(),..Module))
    } Catch ex {
        Return $$$ERROR($$$GeneralError,"SIMULATOR_SNAPSHOT_UNAVAILABLE")
    }
    Return $$$OK
}

Method Trials(orderId As %String, Output trials As %DynamicObject) As %Status
{
    If $TLevel Return $$$ERROR($$$GeneralError,"NO_TRANSACTION_DURING_PROVIDER_IO")
    Try {
        Set args={"orderId":(orderId)}
        Set trials=##class(%DynamicObject).%FromJSON(..Python(..Root,"TRIALS",args.%ToJSON(),..Module))
    } Catch ex {
        Return $$$ERROR($$$GeneralError,"SIMULATOR_TRIALS_UNAVAILABLE")
    }
    Return $$$OK
}

ClassMethod Python(root As %String, command As %String, arguments As %String, module As %String) As %String [ Language = python, Private ]
{
    import json,importlib
    from decimal import Decimal
    Runtime=importlib.import_module(module).Runtime
    runtime=Runtime(root)
    args=json.loads(arguments,parse_float=Decimal)
    if command=="VALIDATE":result={"configured":True}
    elif command=="SUBMIT":result=runtime.submit(args["operation"],args["ticket"])
    elif command=="QUERY":result=runtime.query(args["operation"])
    elif command=="SNAPSHOT":result=runtime.snapshot(args["orderId"])
    elif command=="TRIALS":result=runtime.trials(args["orderId"])
    else:raise ValueError("UNKNOWN_PROVIDER_COMMAND")
    return json.dumps(result,ensure_ascii=False,separators=(",",":"),allow_nan=False)
}
}
