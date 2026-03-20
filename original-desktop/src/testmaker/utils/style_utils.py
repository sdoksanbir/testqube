def button_style(color: str) -> str:
    return f"""
        QPushButton {{
            background-color: {color};
            color: #1d1d1d;
            border-radius: 8px;
            padding: 12px;
            font-weight: bold;
            font-size: 14px;
            border: 1px solid {color};
        }}
        QPushButton:hover {{
            background-color: white;
            color: {color};
            border: 2px solid {color};
        }}
    """

def thumb_style() -> str:
    return "background-color:white; border-radius: 8px;"
