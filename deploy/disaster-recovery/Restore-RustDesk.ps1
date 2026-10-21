[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$BackupPath,
    [Parameter(Mandatory=$true)][string]$TargetHost,
    [string]$TargetDirectory = '/srv/rustdesk-herstel'
)
$ErrorActionPreference = 'Stop'

function Quote-Sh([string]$Value) {
    if ($Value.Contains("`n") -or $Value.Contains("`r")) { throw 'Geen nieuwe regels in argumenten.' }
    return "'" + $Value.Replace("'", "'" + '"' + "'" + '"' + "'") + "'"
}
function Invoke-Remote([string]$Command, [string]$Step) {
    Write-Host ('[' + $TargetHost + '] ' + $Step)
    $lines = @(& ssh -T -n -o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=15 -o ServerAliveCountMax=4 $TargetHost $Command)
    if ($LASTEXITCODE -ne 0) {
        throw ('Stap: ' + $Step + '; SSH-exitcode: ' + $LASTEXITCODE + '. Niet automatisch herhaald; een herstelactie kan op de host nog lopen.')
    }
    return ($lines -join "`n").Trim()
}
function Copy-ToTarget([string]$From, [string]$RemotePath) {
    & scp -q -o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=15 -o ServerAliveCountMax=4 $From ($TargetHost + ':' + $RemotePath)
    if ($LASTEXITCODE -ne 0) { throw 'SCP-overdracht mislukt. De lokale back-up blijft behouden.' }
}

if ($TargetHost -notmatch '\A[a-zA-Z0-9_][a-zA-Z0-9_.@-]*\z') { throw 'Gebruik een SSH-configalias of user@host.' }
if (-not $TargetDirectory.StartsWith('/') -or $TargetDirectory -eq '/' -or $TargetDirectory.Contains("`n") -or $TargetDirectory.Contains("`r")) {
    throw 'Gebruik een nieuwe absolute Linux-map, bijvoorbeeld /srv/rustdesk-herstel.'
}
$TargetDirectory = $TargetDirectory.TrimEnd('/')
foreach ($program in @('ssh','scp')) { Get-Command $program -ErrorAction Stop | Out-Null }
$archive = (Resolve-Path -LiteralPath $BackupPath -ErrorAction Stop).Path
if (-not (Test-Path -LiteralPath $archive -PathType Leaf)) { throw 'BackupPath moet een bestand zijn.' }
$checksumFile = $archive + '.sha256'
if (-not (Test-Path -LiteralPath $checksumFile -PathType Leaf)) { throw 'Het bijbehorende .sha256-bestand ontbreekt naast de back-up.' }
$expected = ((Get-Content -LiteralPath $checksumFile -Raw).Trim() -split '\s+')[0]
if ($expected -notmatch '\A[a-fA-F0-9]{64}\z') { throw 'Ongeldige SHA256 in het checksum-bestand.' }
Write-Host 'Bestaande lokale back-up controleren...'
if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $expected) { throw 'Lokale SHA256 wijkt af; niets verstuurd.' }
$helper = Join-Path $PSScriptRoot 'rustdesk-dr.py'
if (-not (Test-Path -LiteralPath $helper -PathType Leaf)) { throw 'rustdesk-dr.py ontbreekt naast dit script.' }

$remoteFolder = $null
$completed = $false
try {
    Invoke-Remote 'sudo -n true && command -v python3 && docker compose version' 'Voorwaarden op doelhost controleren' | Write-Host
    Invoke-Remote ('sudo -n test ! -e ' + (Quote-Sh $TargetDirectory)) 'Controleren dat herstelmap nog niet bestaat' | Out-Null
    $remoteFolder = Invoke-Remote 'mktemp -d /tmp/joey-rustdesk-restore.XXXXXXXX' 'Private tijdelijke uploadmap maken'
    if ($remoteFolder -notmatch '\A/tmp/joey-rustdesk-restore\.[a-zA-Z0-9]+\z') {
        $remoteFolder = $null
        throw 'Onverwacht tijdelijk pad ontvangen.'
    }
    Write-Host 'Herstelhelper en bestaande back-up uploaden...'
    Copy-ToTarget $helper ($remoteFolder + '/rustdesk-dr.py')
    Copy-ToTarget $archive ($remoteFolder + '/backup.tar.gz')
    $command = 'sudo -n python3 ' + (Quote-Sh ($remoteFolder + '/rustdesk-dr.py')) + ' restore --archive ' + (Quote-Sh ($remoteFolder + '/backup.tar.gz')) + ' --sha256 ' + $expected + ' --target-dir ' + (Quote-Sh $TargetDirectory)
    $output = Invoke-Remote $command 'Back-up valideren, uitpakken en Docker-images laden (niet starten)'
    $json = @($output -split '\r?\n' | Where-Object { $_.StartsWith('{') }) | Select-Object -Last 1
    if (-not $json) { throw 'Geen herstelbevestiging ontvangen.' }
    $result = $json | ConvertFrom-Json
    if ($result.staged -ne $TargetDirectory -or $result.containers_started -ne $false) { throw 'Onverwachte herstelbevestiging ontvangen.' }
    $completed = $true
    $activation = 'sudo python3 ' + (Quote-Sh ($TargetDirectory.TrimEnd('/') + '/rustdesk-dr.py')) + ' activate --stack-dir ' + (Quote-Sh $TargetDirectory)
    $instructions = @(
        'HERSTEL KLAAR; GEEN CONTAINERS GESTART.',
        ('Doelhost: ' + $TargetHost),
        ('Herstelmap: ' + $TargetDirectory),
        ('Compose-project: ' + $result.project),
        'Controleer proxy/HTTPS, poorten en firewall op deze host.',
        'Bij failover: schakel eerst de oude primaire server uit of isoleer hem.',
        ('Maak dan verbinding: ssh ' + $TargetHost),
        'Voer op de doelhost uit:',
        $activation,
        'Controleer services/logs en zet vervolgens de publieke A/AAAA-DNS om.',
        'Voer een echte verbindingstest met twee clients uit.'
    )
    $receipt = $archive + '.restore-' + [Guid]::NewGuid().ToString('N').Substring(0,8) + '.txt'
    $instructions | Write-Host
    $instructions | Set-Content -LiteralPath $receipt -Encoding utf8
    Write-Host ('Herstelinstructies opgeslagen: ' + $receipt)
} finally {
    if ($remoteFolder -and $completed) {
        $cleanup = 'rm -- ' + (Quote-Sh ($remoteFolder + '/rustdesk-dr.py')) + ' ' + (Quote-Sh ($remoteFolder + '/backup.tar.gz')) + ' && rmdir -- ' + (Quote-Sh $remoteFolder)
        try { Invoke-Remote $cleanup 'Tijdelijke uploadbestanden opruimen' | Out-Null } catch { Write-Warning ('Tijdelijke uploadmap niet opgeruimd: ' + $remoteFolder) }
    } elseif ($remoteFolder) {
        Write-Warning ('Herstel niet bevestigd. Tijdelijke bestanden blijven voor onderzoek staan in ' + $remoteFolder + '; een gedeeltelijke herstelmap kan ook bestaan.')
    }
}
