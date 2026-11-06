/// Internal adapter contract. Implementations must be installed trusted code.
/// Never select an adapter, endpoint or receipt from agent/browser input.
/// Query has no sending side effect. Submit returns only after destination commit.
Class Chronos.Recovery.Provider Extends %RegisteredObject [ Abstract ]
{
Method Submit(operation As %DynamicObject, ticket As %DynamicObject, Output receipt As %DynamicObject) As %Status [ Abstract ]
{
}
Method Query(operation As %DynamicObject, Output receipt As %DynamicObject) As %Status [ Abstract ]
{
}
}
