# Windows: first identify the Kraken's current USBPcap interface and USB address.
param(
    [Parameter(Mandatory=$true)][string]$Interface,
    [Parameter(Mandatory=$true)][int]$DeviceAddress,
    [int]$Duration = 15,
    [string]$Output = (Join-Path $PSScriptRoot '..\captures\windows\cam-frames-new.pcapng'),
    [string]$Tshark = 'C:\Program Files\Wireshark\tshark.exe'
)
$ErrorActionPreference = 'Stop'
if (Test-Path $Output) { throw "Refusing to overwrite existing capture: $Output" }
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Output) | Out-Null
$extcap = 'extcap.' + ($Interface -replace '[^a-zA-Z0-9]', '_').ToLower()
& $Tshark -i $Interface -o "${extcap}.devices:$DeviceAddress" `
    -o "${extcap}.capturefromalldevices:false" -o "${extcap}.capturefromnewdevices:false" `
    -o "${extcap}.snaplen:2097152" -o "${extcap}.bufferlen:16777216" `
    -a "duration:$Duration" -w $Output
if ($LASTEXITCODE -ne 0) { throw "tshark exited with $LASTEXITCODE" }
