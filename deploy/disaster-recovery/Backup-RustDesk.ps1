[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$SourceHost,
    [string]$SourceDirectory = '/home/joey/docker/rustdesk',
    [string]$DestinationDirectory = (Join-Path $PSScriptRoot 'backups'),
    [string]$StandbyHost,
    [string]$StandbyBaseDirectory = '/srv/rustdesk-recovery'
)
$ErrorActionPreference = 'Stop'

function Quote-Sh([string]$Value) {
    if ($Value.Contains("`n") -or $Value.Contains("`r")) { throw 'Geen nieuwe regels in argumenten.' }
    # POSIX shell single quoting, including embedded apostrophes.
    return "'" + $Value.Replace("'", "'" + '"' + "'" + '"' + "'") + "'"
}
function Check-Host([string]$Value) {
    if ($Value -notmatch '\A[a-zA-Z0-9_][a-zA-Z0-9_.@-]*\z') {
        throw 'Gebruik een SSH-configalias of user@host (IPv6 via SSH-configalias).'
    }
}
function Invoke-Remote([string]$Target, [string]$Command) {
    $lines = @(& ssh -o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=15 -o ServerAliveCountMax=4 $Target $Command)
    if ($LASTEXITCODE -ne 0) { throw ('SSH-opdracht mislukt op ' + $Target + '. Controleer bovenstaande foutmelding.') }
    return ($lines -join "`n").Trim()
}
function Copy-Checked([string]$From, [string]$To) {
    & scp -q -o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=15 -o ServerAliveCountMax=4 $From $To
    if ($LASTEXITCODE -ne 0) { throw 'SCP-overdracht mislukt; reeds gemaakte bronback-up blijft bewaard.' }
}
function Upload-Helper([string]$Target) {
    $folder = Invoke-Remote $Target 'mktemp -d /tmp/joey-rustdesk-tools.XXXXXXXX'
    if ($folder -notmatch '\A/tmp/joey-rustdesk-tools\.[a-zA-Z0-9]+\z') { throw 'Onverwacht tijdelijk pad van SSH-server.' }
    Copy-Checked (Join-Path $PSScriptRoot 'rustdesk-dr.py') ($Target + ':' + $folder + '/rustdesk-dr.py')
    return $folder
}
function Read-RemoteJson([string]$Text) {
    # SSH login banners may precede the helper's final machine-readable result.
    $line = @($Text -split '\r?\n' | Where-Object { $_.StartsWith('{') }) | Select-Object -Last 1
    if (-not $line) { throw 'Geen voltooiingsbevestiging van de server ontvangen.' }
    return ($line | ConvertFrom-Json)
}

$sourceTools = $null
$standbyTools = $null
try {
    Check-Host $SourceHost
    if ($StandbyHost) { Check-Host $StandbyHost }
    if (-not $SourceDirectory.StartsWith('/') -or -not $StandbyBaseDirectory.StartsWith('/')) {
        throw 'Gebruik absolute Linux-paden, bijvoorbeeld /home/joey/docker/rustdesk, geen ~.'
    }
    foreach ($program in @('ssh','scp')) { Get-Command $program -ErrorAction Stop | Out-Null }
    if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'rustdesk-dr.py'))) { throw 'rustdesk-dr.py ontbreekt naast dit script.' }
    New-Item -ItemType Directory -Force -Path $DestinationDirectory | Out-Null
    $destination = (Resolve-Path -LiteralPath $DestinationDirectory).Path
    Write-Host 'Bronverbinding controleren; SSH-key en sudo zonder prompt zijn vereist...'
    Invoke-Remote $SourceHost 'sudo -n true && command -v python3 && docker compose version' | Write-Host
    $sourceTools = Upload-Helper $SourceHost
    Write-Host 'Back-up maken. De broncontainers worden kort gestopt en daarna weer gestart...'
    $command = 'sudo -n python3 ' + (Quote-Sh ($sourceTools + '/rustdesk-dr.py')) + ' backup --stack-dir ' + (Quote-Sh $SourceDirectory)
    $result = Read-RemoteJson (Invoke-Remote $SourceHost $command)
    if ($result.archive -notmatch '\A/var/tmp/rustdesk-backup-[a-zA-Z0-9_.-]+\.tar\.gz\z' -or $result.sha256 -notmatch '\A[a-f0-9]{64}\z') {
        throw 'Onverwacht back-upresultaat; geen overdracht uitgevoerd.'
    }
    $name = [IO.Path]::GetFileName($result.archive)
    $local = Join-Path $destination $name
    if (Test-Path -LiteralPath $local) { throw 'Lokaal back-upbestand bestaat al; niet overschreven.' }
    $partial = $local + '.part'
    if (Test-Path -LiteralPath $partial) { throw 'Er bestaat al een onvolledige download op deze locatie.' }
    Write-Host 'Bron is weer gestart. Back-up naar deze Windows-pc kopieren...'
    Copy-Checked ($SourceHost + ':' + $result.archive) $partial
    if ((Get-Item -LiteralPath $partial).Length -ne [long]$result.bytes -or (Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash -ne $result.sha256) {
        throw 'Lokale download wijkt af. .part en de bronback-up blijven staan voor onderzoek.'
    }
    Move-Item -LiteralPath $partial -Destination $local
    ($result.sha256 + '  ' + $name) | Set-Content -LiteralPath ($local + '.sha256') -Encoding ascii
    Write-Host ('Back-up geverifieerd: ' + $local)
    # Only remove the generated remote archive after the verified local copy exists.
    Invoke-Remote $SourceHost ('rm -- ' + (Quote-Sh $result.archive)) | Out-Null
    if ($StandbyHost) {
        Invoke-Remote $StandbyHost 'sudo -n true && command -v python3 && docker compose version' | Write-Host
        $standbyTools = Upload-Helper $StandbyHost
        $remoteCopy = $standbyTools + '/' + $name
        Copy-Checked $local ($StandbyHost + ':' + $remoteCopy)
        $stage = $StandbyBaseDirectory.TrimEnd('/') + '/' + $name.Replace('.tar.gz','')
        $command = 'sudo -n python3 ' + (Quote-Sh ($standbyTools + '/rustdesk-dr.py')) + ' restore --archive ' + (Quote-Sh $remoteCopy) + ' --sha256 ' + $result.sha256 + ' --target-dir ' + (Quote-Sh $stage)
        $staged = Read-RemoteJson (Invoke-Remote $StandbyHost $command)
        $activation = 'sudo python3 ' + (Quote-Sh ($staged.staged + '/rustdesk-dr.py')) + ' activate --stack-dir ' + (Quote-Sh $staged.staged)
        $instructions = @(
            'BACK-UP KLAARGEZET; RESERVECONTAINERS ZIJN NIET GESTART.',
            ('SSH-host: ' + $StandbyHost),
            ('Herstelmap: ' + $staged.staged),
            'Bij failover eerst de primaire server aantoonbaar uitschakelen/isoleren.',
            'Voer daarna op de reservehost uit:',
            $activation,
            'Controleer poorten, proxy/HTTPS en logs; zet daarna publieke A/AAAA-DNS om.'
        )
        $instructions | Set-Content -LiteralPath ($local + '.standby.txt') -Encoding utf8
        $instructions | Write-Host
        Invoke-Remote $StandbyHost ('rm -- ' + (Quote-Sh $remoteCopy)) | Out-Null
    }
    Write-Host 'Klaar. De back-up bevat de PRIVATE serverkey: bewaar hem vertrouwelijk en buiten GitHub.'
} finally {
    # No recursive deletion: remove only our uploaded helper and then its empty folder.
    foreach ($entry in @(@($SourceHost,$sourceTools),@($StandbyHost,$standbyTools))) {
        if ($entry[0] -and $entry[1]) {
            $cleanup = 'rm -f -- ' + (Quote-Sh ($entry[1] + '/rustdesk-dr.py')) + '; rmdir -- ' + (Quote-Sh $entry[1])
            try { Invoke-Remote $entry[0] $cleanup | Out-Null } catch { Write-Warning 'Tijdelijke helpermap niet volledig opgeruimd; er kan een hersteldownload in staan.' }
        }
    }
}
