def format_cfa(value) -> str:
    """
    Format a numeric value as FCFA with thousands separators and no decimals.
    Examples:
    - 1500 -> "1 500"
    - 1200000.4 -> "1 200 000"
    """
    try:
        # Round to nearest integer and format with comma, then replace with spaces
        rounded = int(round(float(value)))
        return format(rounded, ",").replace(",", " ")
    except (ValueError, TypeError):
        # Fallback to string if not a number
        return str(value)