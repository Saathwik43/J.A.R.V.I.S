from dotenv import load_dotenv
from mem0 import MemoryClient
import logging
import json

load_dotenv()
user_name="Saathwik"
mem0=MemoryClient()

def add_memory():

    messages_formatted=[
        {
            "role":"user",
            "content":"My favorite food is biriyani."
        },
        {
            "role":"assistant",
            "content":"That's great to hear! Biriyani is a delicious dish with a rich blend of spices and flavors. Do you have a favorite type of biriyani, like chicken, mutton, or vegetable?"
        },
        {
            "role":"user",
            "content":"I like chicken biriyani the most."
        },
        {
            "role":"assistant",
            "content":"That's great to hear sir!"
        }
    ]
    mem0.add(messages_formatted, user_id=user_name)


def get_memory_by_query():
    mem0=MemoryClient()
    query="what is {user_name}'s favorite food?"
    response=mem0.search(query, filters={"user_id": user_name})

    memories=[
        {
            "memory":result["memory"],
            "updated_at":result["updated_at"]
        }
        for result in response.get("results", [])
    ]
    memories_str=json.dumps(memories,indent=4)
    logging.info(f"Memories retrieved for query '{query}': {memories_str}")
    return memories_str


if __name__=="__main__":
    logging.basicConfig(level=logging.INFO)
    get_memory_by_query()