param(
    [switch]$StopPortConflicts
)

$ArgsForNode = @()
if ($StopPortConflicts) {
    $ArgsForNode += "--stop-port-conflicts"
}

node "$PSScriptRoot\start_local.js" @ArgsForNode
exit $LASTEXITCODE
