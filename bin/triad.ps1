# PowerShell wrapper for Triad CLI
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RemainingArgs
)

& python "C:\Users\micha\.agents\triad\triad_engine.py" @RemainingArgs
