import replicate

from .config import settings

# make sure we set the replicate API token
replicate.api_token = settings.replicate_api_token


def generate_image(input_prompt: str) -> str:
    """Generate an image from a prompt."""
    input = {
        "prompt": input_prompt,
        "seed": 42,
        "guidance_scale": 7.5,
    }
    output = replicate.run(
        "sundai-club/octo-gen:492c0cb1436dd356c03b4a678087ede097f11e00f5348cc8889e2c34718b68de",
        input=input,
    )
    return output[0].url
