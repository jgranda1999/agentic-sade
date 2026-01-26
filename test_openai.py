from agents import Agent, Runner

agent = Agent(name="Assistant", instructions="You are a helpful assistant")

result = Runner.run_sync(agent, "Who is Big H in WW2?")
print(result.final_output)

# Code within the code,
# Functions calling themselves,
# Infinite loop's dance.