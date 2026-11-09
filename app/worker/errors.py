class UnprocessableMedia(Exception):
    """The file itself is the problem, so retrying would not help.

    The message is shown to the user, so keep it plain and free of internals.
    """
