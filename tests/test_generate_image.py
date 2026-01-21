from workshop1.replicate_client import generate_image

def test_generate_image():
    """Test generating an image."""
    prompt = "OCTGUY octopus underwater photorealistic."
    image_url = generate_image(prompt)
    print(image_url)
    assert image_url is not None
    assert len(image_url) > 0
    # assert image_url.startswith("https://")
    # assert image_url.endswith(".png")
