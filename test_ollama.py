import ollama

print("Sending request...")

response = ollama.chat(
    model="gemma4:26b",
    messages=[
        {
            "role": "user",
            "content": "Say hello in one sentence."
        }
    ],
)

print("Response:")
print(response["message"]["content"])