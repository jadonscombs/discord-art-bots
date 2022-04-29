"""
Small collection of async(hronous) methods/functions/utilities.
"""


async def react_success(ctx):
    """
    React to the supplied ctx.message with a 'check mark'
    """
    await ctx.message.add_reaction("\N{HEAVY CHECK MARK}")


async def react_fail(ctx):
    """
    React to the supplied ctx.message with a 'cross mark'
    """
    await ctx.message.add_reaction("\N{CROSS MARK}")
