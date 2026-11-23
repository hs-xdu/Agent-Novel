import json
import os
import tiktoken
from prompts import SYSTEM, TASKS


def request_cost(task, context, schema=None, api_mode='responses'):
    instruction=SYSTEM+'\n'+TASKS[task]
    if schema is not None:
        instruction+='\n只输出 JSON，必须符合此 schema：'+json.dumps(schema.model_json_schema(),ensure_ascii=False)
    return 2*len(tiktoken.get_encoding('cl100k_base').encode(instruction+context,disallowed_special=()))


def input_budget():
    return int(os.getenv('NOVEL_CONTEXT_TOKENS','24000'))-int(os.getenv('NOVEL_OUTPUT_TOKENS','6000'))
