from cartesia import Cartesia

# Initialize the client
client = Cartesia(api_key="sk_car_kYQWpaXLPRU3H9tmvWqf61")

text = "Hey! सुनो ना... मुझे तुमसे कुछ पूछना था। तुम्हें क्या लगता है, हम पहली बार कहाँ मिले थे? I mean... seriously! ऐसा लगता है जैसे मैं तुम्हें forever से जानती हूँ! और हाँ... अपना ज़्यादा ध्यान रखा करो, okay? I love you."

print("Sending request to Cartesia...")

# Generate the audio using the new 2.0 SDK format
response = client.tts.generate(
    model_id="sonic-3.5",
    transcript=text,
    voice={
        "mode": "id",
        "id": "faf0731e-dfb9-4cfc-8119-259a79b27e12" # Paste the ID of the female voice you liked
    },
    language="hi",
    output_format={
        "container": "wav",
        "encoding": "pcm_f32le",
        "sample_rate": 44100,
    },
)

# The response object now has a built-in method to save the file!
response.write_to_file("cartesia_final_test.wav")

print("✅ Success! Audio saved as 'cartesia_final_test.wav'.")