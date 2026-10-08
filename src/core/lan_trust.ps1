param([Parameter(Mandatory=$true)][string]$CertificatePath)
$ErrorActionPreference = 'Stop'
$raw = [IO.File]::ReadAllText($CertificatePath)
if ($raw -match 'PRIVATE KEY') { throw 'Private keys are not accepted.' }
$base64 = $raw.Replace('-----BEGIN CERTIFICATE-----','').Replace('-----END CERTIFICATE-----','')
$cert = [System.Security.Cryptography.X509Certificates.X509Certificate2]::new([Convert]::FromBase64String($base64))
if ($cert.NotAfter -lt [DateTime]::Now -or $cert.NotBefore -gt [DateTime]::Now) { throw 'Certificate is not valid now.' }
$ca = @($cert.Extensions | Where-Object {$_.Oid.Value -eq '2.5.29.19'})
if ($ca.Count -ne 1 -or -not $ca[0].CertificateAuthority) { throw 'Expected a CA certificate.' }
$store = New-Object System.Security.Cryptography.X509Certificates.X509Store('Root','CurrentUser')
try {
    $store.Open('ReadWrite')
    $existing = $store.Certificates.Find('FindByThumbprint',$cert.Thumbprint,$false)
    if ($existing.Count -eq 0) { $store.Add($cert) }
} finally { $store.Close() }
