"""
Bedrock smoke test.

    python test.py

NOTE: AnthropicBedrockMantle does NOT work on this account. The org's Service
Control Policy carries an EXPLICIT DENY on `bedrock-mantle:CreateInference`:

    arn:aws:organizations::496747445669:policy/o-z1ighb6yyh/
      service_control_policy/p-1sclicmp

An SCP explicit deny cannot be overridden by IAM permissions, and it is not
region-specific. So we use the legacy `AnthropicBedrock` client, which goes to
bedrock-runtime InvokeModel — a different action the SCP permits.

That path needs the INFERENCE PROFILE id (the `us.` prefix), not the bare model
id: Claude Haiku 4.5 is registered as INFERENCE_PROFILE-only in this region.
"""
import os

from anthropic import AnthropicBedrock

MODEL = os.getenv("MODEL_PREDICT", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
REGION = os.getenv("BEDROCK_REGION", "us-east-1")

client = AnthropicBedrock(
    aws_profile=os.getenv("AWS_PROFILE", "hackathon"),
    aws_region=REGION,
)

message = client.messages.create(
    model=MODEL,
    max_tokens=64,
    messages=[{"role": "user", "content": "What is Amazon Bedrock?"}],
)
print(message.content[0].text)
print(f"\n[{MODEL} @ {REGION}  in={message.usage.input_tokens} "
      f"out={message.usage.output_tokens}]")
