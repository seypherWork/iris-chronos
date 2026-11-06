Include %occStatus

/// Native outbound connector for the installation-pinned inference guard.
Class Chronos.Agent.GuardAdapter Extends Ens.OutboundAdapter
{

Method OpenAgentSession(baseURL As %String, model As %String, instructions As %String, timeoutSeconds As %Integer, options As %DynamicObject, Output provider As %RegisteredObject, Output agent As %RegisteredObject, Output session As %RegisteredObject) As %Status
{
    Set settings={"api_key":"ollama","base_url":(baseURL),"http_config":{"connect_timeout_secs":1,"request_timeout_secs":(timeoutSeconds)}}
    Set provider=##class(%AI.Provider).Create("openai",settings)
    Set agent=##class(%AI.Agent).%New(provider)
    Set agent.Model=model,agent.SystemPrompt=instructions,agent.Temperature=0
    Set session=agent.CreateSession(options)
    Return $$$OK
}

Method Exchange(agent As %RegisteredObject, session As %RegisteredObject, inputJSON As %String) As %RegisteredObject
{
    Return agent.Chat(session,inputJSON)
}

}
