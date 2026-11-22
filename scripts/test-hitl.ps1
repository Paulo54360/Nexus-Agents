<#
.SYNOPSIS
    Teste en local la stack Nexus (healthcheck + graphe multi-agents + pause/validation HITL).
.EXAMPLE
    .\scripts\test-hitl.ps1
#>

$ErrorActionPreference = "Stop"
$BaseUrl = "http://127.0.0.1:8000"
$ThreadId = "demo-local-$(Get-Date -Format 'HHmmss')"

Write-Host "`n[1/3] Vérification de /health..." -ForegroundColor Cyan
$health = Invoke-RestMethod -Uri "$BaseUrl/health" -Method Get
$health | ConvertTo-Json

Write-Host "`n[2/3] Envoi d'une demande qui déclenche le Supervisor + Agent Gmail + HITL..." -ForegroundColor Cyan
$chatBody = @{
    thread_id = $ThreadId
    message   = "Lis mes mails non lus, puis appelle directement gmail_send_email (sans créer de brouillon) pour répondre au recruteur et confirmer ma disponibilité mardi à 14h."
} | ConvertTo-Json -Depth 5

$response = Invoke-RestMethod -Uri "$BaseUrl/chat" -Method Post -ContentType "application/json; charset=utf-8" -Body ([System.Text.Encoding]::UTF8.GetBytes($chatBody))
Write-Host "Statut : $($response.status)" -ForegroundColor Yellow
Write-Host "Réponse : $($response.reply)"

if ($response.status -eq "approval_required") {
    Write-Host "`nAction en attente de validation (Human-in-the-Loop) :" -ForegroundColor Magenta
    $response.pending_approval | ConvertTo-Json -Depth 5

    $choice = Read-Host "`nVeux-tu VALIDER l'envoi de ce mail ? (o/n)"
    $approved = ($choice -match "^[oOyY]")

    Write-Host "`n[3/3] Reprise du graphe LangGraph (approved=$approved)..." -ForegroundColor Cyan
    $approvalBody = @{
        approved = $approved
        reason   = if ($approved) { "Validé depuis test-hitl.ps1" } else { "Refusé par l'utilisateur" }
    } | ConvertTo-Json

    $final = Invoke-RestMethod -Uri "$BaseUrl/approvals/$ThreadId" -Method Post -ContentType "application/json; charset=utf-8" -Body ([System.Text.Encoding]::UTF8.GetBytes($approvalBody))
    Write-Host "`nRésultat final ($($final.status)) :" -ForegroundColor Green
    Write-Host $final.reply
} else {
    Write-Host "`nLe graphe s'est terminé sans pause HITL (vérifie si l'agent a préféré créer un brouillon)." -ForegroundColor Green
}
