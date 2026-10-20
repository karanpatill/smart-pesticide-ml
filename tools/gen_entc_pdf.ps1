$edge = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
$src = "file:///d:/smart-pesticide-ml/docs/ENTC_SOFTWARE_AI_TECHNICAL_GUIDE.html"
$dst = "C:\Users\kpvlo\Downloads\SMART_PESTICIDE_GOOGLE_DRIVE_HANDOVER\ENTC_SOFTWARE_AI_TECHNICAL_GUIDE.pdf"
$reports_dst = "d:\smart-pesticide-ml\reports\ENTC_SOFTWARE_AI_TECHNICAL_GUIDE.pdf"

$args = @(
    "--headless",
    "--disable-gpu",
    "--no-pdf-header-footer",
    "--print-to-pdf=$dst",
    $src
)

Start-Process -FilePath $edge -ArgumentList $args -Wait
Start-Sleep -Seconds 2

if (Test-Path $dst) {
    Copy-Item -Force $dst $reports_dst
    Get-Item $dst | Select-Object Name, Length, LastWriteTime
    Write-Host "PDF Generation Succeeded!"
} else {
    Write-Error "PDF was not created!"
}
