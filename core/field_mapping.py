from __future__ import annotations

# Field mapping configuration for ShopSite XML import
# Maps ShopSite XML fields to the specific fields needed by the product editor

# Core product fields that the editor ACTUALLY uses (optimized for performance)
EDITOR_FIELD_MAPPING = {
    # Editor Field -> List of possible ShopSite field names (in priority order)
    "SKU": ["SKU", "Name"],
    "Name": ["Name"],
    "Brand": ["ProductField16", "Brand"],
    "Weight": ["Weight"],
    "Special_Order": ["ProductField11"],
    "Category": ["ProductField24"],
    "Product_Type": ["ProductField25"],
    "Product_On_Pages": ["ProductOnPages", "Product On Pages"],
    "Graphic": ["Graphic"],  # Main product image
    "MoreInfoImage1": ["MoreInfoImage1"],
    "MoreInfoImage2": ["MoreInfoImage2"],
    "MoreInfoImage3": ["MoreInfoImage3"],
    "MoreInfoImage4": ["MoreInfoImage4"],
    "MoreInfoImage5": ["MoreInfoImage5"],
    "MoreInfoImage6": ["MoreInfoImage6"],
}

# Fields to always include (even if empty) for database integrity
REQUIRED_FIELDS = [
    "Name",
    "Brand",
    "Weight",  # Special_Order removed - only store when "yes"
    "Category",
    "Product_Type",
    "Product_On_Pages",
    "Graphic",
]

# Image-related fields (for collecting all product images)
IMAGE_FIELDS = [
    "Graphic",
    "MoreInfoImage1",
    "MoreInfoImage2",
    "MoreInfoImage3",
    "MoreInfoImage4",
    "MoreInfoImage5",
    "MoreInfoImage6",
    "MoreInfoImage7",
    "MoreInfoImage8",
    "MoreInfoImage9",
    "MoreInfoImage10",
]


def map_shopsite_fields(product_data):
    """
    Map ShopSite XML fields to editor format, keeping only relevant fields.

    Args:
        product_data: Dict of all ShopSite fields from XML

    Returns:
        Dict with only the mapped fields needed by the editor
    """
    mapped_product: dict[str, str | list[str]] = {}

    # Map each editor field from possible ShopSite field names
    for editor_field, shopsite_fields in EDITOR_FIELD_MAPPING.items():
        value = None
        for shopsite_field in shopsite_fields:
            if product_data.get(shopsite_field):
                value = product_data[shopsite_field]
                break

        # Special handling for Category - ensure unique values
        if editor_field == "Category" and value:
            # Split by "|", deduplicate, and rejoin with "|"
            categories = [cat.strip() for cat in str(value).split("|") if cat.strip()]
            unique_categories = list(dict.fromkeys(categories))  # Preserve order while removing duplicates
            value = "|".join(unique_categories)

        # Special handling for Product_Type - ensure unique values
        if editor_field == "Product_Type" and value:
            # Split by "|", deduplicate, and rejoin with "|"
            types = [pt.strip() for pt in str(value).split("|") if pt.strip()]
            unique_types = list(dict.fromkeys(types))  # Preserve order while removing duplicates
            value = "|".join(unique_types)

        # Special handling for Product_On_Pages - ensure "|" separator and unique values
        if editor_field == "Product_On_Pages" and value:
            # Split by comma, deduplicate, and rejoin with "|" to standardize separator
            pages = [page.strip() for page in str(value).split(",") if page.strip()]
            unique_pages = list(dict.fromkeys(pages))  # Preserve order while removing duplicates
            value = "|".join(unique_pages)

        # Special handling for Special_Order
        if editor_field == "Special_Order":
            # Check if the field exists in the source data (even if empty)
            field_exists = any(shopsite_field in product_data for shopsite_field in shopsite_fields)
            if field_exists:
                raw_value = product_data.get(shopsite_fields[0], "")  # Get the actual value
                if str(raw_value).lower().strip() == "yes":
                    mapped_product[editor_field] = "yes"
                else:
                    # Store as empty string if it was blank in source
                    mapped_product[editor_field] = ""
            # Skip if field doesn't exist at all
            continue

        # Ensure we have a value for required fields
        if editor_field in REQUIRED_FIELDS and value is None:
            value = ""

        if value is not None:
            mapped_product[editor_field] = value

    # Collect all available images
    images = []
    for img_field in IMAGE_FIELDS:
        img_url = product_data.get(img_field, "").strip()
        if img_url and img_url.lower() != "none":
            images.append(img_url)

    if images:
        mapped_product["Image_URLs"] = images

    return mapped_product
