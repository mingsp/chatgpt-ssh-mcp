param(
    [string]$ProfileName = 'chatgpt-ssh-mcp',
    [string]$TunnelClient = 'tunnel-client',
    [ValidateRange(1, 65535)]
    [int]$HealthPort = 18743
)

$ErrorActionPreference = 'Stop'
$client = (Get-Command -Name $TunnelClient -CommandType Application -ErrorAction Stop).Source
$keyEnteredHere = -not $env:CONTROL_PLANE_API_KEY
try {
    if ($keyEnteredHere) {
        $secret = Read-Host 'OpenAI tunnel runtime API key (hidden)' -AsSecureString
        $env:CONTROL_PLANE_API_KEY = [System.Net.NetworkCredential]::new('', $secret).Password
        $secret.Dispose()
    }
    if (-not $env:CONTROL_PLANE_API_KEY) {
        throw 'A tunnel runtime API key is required.'
    }
    & $client run --profile $ProfileName --health.listen-addr "127.0.0.1:$HealthPort"
    if ($LASTEXITCODE -ne 0) {
        throw "Tunnel client exited with code $LASTEXITCODE."
    }
}
finally {
    if ($keyEnteredHere) {
        Remove-Item Env:CONTROL_PLANE_API_KEY -ErrorAction SilentlyContinue
    }
}
