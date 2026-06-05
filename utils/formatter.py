def format_output(text):
    # basic cleanup
    text = text.strip()

    # fix excessive new lines
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")

    return text
