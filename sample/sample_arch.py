#Importing Libraries
from agents import Agent, Runner, WebSearchTool, trace
from agent_prompts import (
    get_orchestrator_prompt,
    get_eligibility_prompt,
    get_policy_prompt,
    get_grant_writer_prompt,
    get_general_prompt,
    get_grant_strategy_advice_prompt,
    get_find_grant_opportunity_prompt,
    get_foundation_matcher_prompt,
    get_generate_reports_prompt,
    get_propublica_api_prompt
)
from faiss_matcher_tool import faiss_matcher
import os
from faiss_matcher_tool import NonprofitMatcher
from typing import Callable, Dict, Any, Optional
import logging
from propublica_api_tool import propublica_api

logger = logging.getLogger(__name__)

#Agent Definitions
def create_agents(email_content: str, url: Optional[str], nonprofit_context: Dict[str, Any]) -> Agent:
    """
    Creates and returns all agent instances
    
    Args:
        email_content: The full email content
        url: Optional URL extracted from email
        nonprofit_context: Dictionary containing nonprofit information
    """
    faiss_tool = faiss_matcher(email_content, nonprofit_context)
    
    logging.info(f"Nonprofit Context: {nonprofit_context}")
    try:
        # Initialize FAISS matcher if needed
        if not os.path.exists('vector/nonprofit_index.faiss'):
            matcher = NonprofitMatcher()
            matcher.load_and_index_data('vector/foundations_to_nonprofits.csv')
        
        # Create agents with proper error handling
        location = nonprofit_context.get('location', 'Unknown Location')
        
        #Using ProPublica API to find foundations that match the client's nonprofit cause Agent 
        foundation_search_agent = Agent(
            name="Foundation Matching Search Agent",
            model= "o4-mini",
            instructions=get_propublica_api_prompt(nonprofit_context),
            tools=[propublica_api],
        )
        
        #Eligibility Agent
        eligibility_agent = Agent(
            name="Eligibility Agent",
            model="o3-mini",
            instructions=get_eligibility_prompt(email_content, url, nonprofit_context),
            tools=[WebSearchTool(user_location={"type": "approximate", "city": location})],
        )
        
        #Policy Agent
        policy_agent = Agent(
            name="Policy Agent",
            model= "o4-mini",
            instructions= get_policy_prompt(email_content, nonprofit_context),
        )

        #Grant Writer Agent
        grant_writer_agent = Agent(
            name="Grant Writer Agent",
            model= "o3-mini",
            instructions= get_grant_writer_prompt(email_content, nonprofit_context),
        )
        
        #General Agent
        general_agent = Agent(
            name="General Agent",
            model= "o4-mini",
            instructions= get_general_prompt(email_content, nonprofit_context),
        )
        
        #Grant Strategy Advice Agent
        grant_strategy_advice_agent = Agent(
            name="Grant Strategy Advice Agent",
            model= "o3-mini",
            instructions= get_grant_strategy_advice_prompt(email_content, nonprofit_context),
        )
        
        #Find Grant Opportunity Agent
        find_grant_opportunity_agent = Agent(
            name="Find Grant Opportunity Agent",
            model="o4-mini",
            instructions= get_find_grant_opportunity_prompt(email_content, nonprofit_context),
            tools=[WebSearchTool(user_location={"type": "approximate", "city": location})],
        )

        #Find whihc Foundations Gave Grants to Other Nonprofit Agent 
        foundation_grant_giving_agent = Agent(
            name="Foundation Grant Giving to Nonprofit Agent",
            instructions=get_foundation_matcher_prompt(email_content, nonprofit_context),
            tools=[faiss_tool, WebSearchTool(user_location={"type": "approximate", "city": location})],
        )

        #Generate Reports on Grants Agent
        generate_reports_agent = Agent(
            name="Generate Reports on Grants Agent",
            model="o3-mini",
            instructions=get_generate_reports_prompt(email_content, url, nonprofit_context),
            tools=[WebSearchTool(user_location={"type": "approximate", "city": location})],
        )

        #Orchestrator Agent
        orchestrator_agent = Agent(
            name="Orchestrator Agent",
            model="o3-mini",
            instructions=get_orchestrator_prompt(email_content, nonprofit_context),
            tools=[
                foundation_search_agent.as_tool(
                    tool_name="foundation_matching_search",
                    tool_description=(
                    "Use to look up foundations that match the client's nonprofit cause for possible funding. "
                    "Pass exactly two arguments: `state` and `propublica_query`."
                    )
                ),
                eligibility_agent.as_tool(
                    tool_name="eligibility_agent",
                    tool_description="Check grant eligibility"
                ),
                policy_agent.as_tool(
                    tool_name="policy_agent",
                    tool_description="Check the policy requirements for the grant",
                ),
                grant_writer_agent.as_tool(
                    tool_name="grant_writer_agent",
                    tool_description="Write the grant proposal for the grant",
                ),  
                general_agent.as_tool(
                    tool_name="general_agent",
                    tool_description="General agent that can answer questions about the client's nonprofit or any other questions related to the grant acquisition process or nonprofit sector",
                ),
                grant_strategy_advice_agent.as_tool(
                    tool_name="grant_strategy_advice_agent",
                    tool_description="Provide grant strategy and advice for the client's nonprofit",
                ),
                find_grant_opportunity_agent.as_tool(
                    tool_name="find_grant_opportunity_agent",
                    tool_description="Search the web for relevant grant opportunities matching the client's nonprofit mission and requirements",
                ), 
                foundation_grant_giving_agent.as_tool(
                    tool_name="foundation_grant_giving_agent",
                    tool_description=(
                    "Use a FAISS vector database to search for the foundations that gave out grants to other nonprofits"
                    )
                ),
                generate_reports_agent.as_tool(
                    tool_name="generate_reports_agent",
                    tool_description="Generate reports on grants for the client's nonprofit",
                ),
            ],
        )
        
        return orchestrator_agent
        
    except Exception as e:
        logger.error(f"Error creating agents: {str(e)}")
        raise

def initialize_agents(email_content: str, url: Optional[str], nonprofit_context: Dict[str, Any]):
    """Initialize the agent system"""
    # Check if index exists, if not create it
    index_path = os.path.join(os.path.dirname(__file__), 'vector', 'nonprofit_index.faiss')
    data_path = os.path.join(os.path.dirname(__file__), 'vector', 'nonprofit_data.pkl')
    
    if not os.path.exists(index_path) or not os.path.exists(data_path):
        matcher = NonprofitMatcher()
        csv_path = os.path.join(os.path.dirname(__file__), 'vector', 'foundations_to_nonprofits.csv')
        matcher.load_and_index_data(csv_path)
    
    return create_agents(email_content, url, nonprofit_context)

def function_tool(func: Callable) -> Callable:
    """Decorator to mark a function as a tool"""
    func._is_tool = True
    return func
