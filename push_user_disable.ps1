<#
$scriptDir = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent
$base = Get-Content $scriptDir\Users.txt
$groups = @("Domain Users")
 
foreach ($g in $groups) {
   $diff += (Get-ADGroupMember -Identity $g).sAMAccountName
}
  
$result = (Compare-Object -ReferenceObject $base -DifferenceObject $diff | Where-Object {$_.SideIndicator -eq "<="} | Select-Object -ExpandProperty InputObject) -join ", "
#>

$Event = Get-EventLog -LogName Security -InstanceId 4725 -Newest 1

$body = @{}
$data =  $Event.Message + "`r`n`t"
$timestamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.fffK")

$body.add("data", $data)
$body.add("timestamp", $timestamp)

<#
$body = @{
    data= $Event.Message + "`r`n`t",
    timestamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.fffK")
}
#>

$headers = New-Object "System.Collections.Generic.Dictionary[[String],[String]]"
$headers.Add("Content-Type", 'application/json')

$json = $body | ConvertTo-Json

$response = Invoke-RestMethod 'http://10.0.1.127:8000/adhook' -Headers $headers -Method Post -Body $json 
Exit