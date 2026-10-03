from io import BytesIO
from PIL import Image


def transparent_logo():
    image = Image.new("RGBA", (120, 80), "#ffffff")
    image.paste("#172d2b", (0, 0, 60, 80))
    image.putpixel((119, 79), (0, 0, 0, 0))
    buffer = BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def complete_branding(client, base, headers, *, fields=None, logo=None, reference=None):
    profile = client.get(f"{base}/brand").json()["profile"]
    existing = client.get(f"{base}/branding").json()
    if not logo:
        logo = client.post(f"{base}/branding/assets/logo", headers=headers,
            files={"file": ("transparent-logo.png", transparent_logo(), "image/png")}).json()["id"]
    answers = {"brand_name": "Nile Coffee", "category": "coffee", "audience": "Coffee lovers", "style": "Clean and simple",
        **({k: v for k, v in profile["fields"].items() if k in {"brand_name", "category", "audience", "style"}} if profile else {}), **(fields or {})}
    response = client.put(f"{base}/branding", headers=headers, json={"answers": answers,
        "logo_asset_id": logo, "reference_asset_id": reference})
    assert response.status_code == 200, response.text
    return response.json()
