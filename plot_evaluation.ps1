param([string]$ResultsDirectory = (Join-Path $PSScriptRoot 'results\abc-smoke'))

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms.DataVisualization
Add-Type -AssemblyName System.Drawing
$report = Get-Content -LiteralPath (Join-Path $ResultsDirectory 'summary.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$chart = New-Object System.Windows.Forms.DataVisualization.Charting.Chart
$chart.Width = 1450
$chart.Height = 850
$chart.BackColor = [System.Drawing.Color]::White
$chart.Font = New-Object System.Drawing.Font('Segoe UI', 12)
try {
    $title = $chart.Titles.Add('Actual evaluation | first draft vs validated result | ' + $report.engine)
    $title.Font = New-Object System.Drawing.Font('Segoe UI', 18, [System.Drawing.FontStyle]::Bold)
    $area = New-Object System.Windows.Forms.DataVisualization.Charting.ChartArea('scores')
    $area.AxisY.Minimum = 0
    $area.AxisY.Maximum = 100
    $area.AxisY.Interval = 10
    $area.AxisY.Title = 'Percentage (%)'
    $area.AxisY.MajorGrid.LineColor = [System.Drawing.Color]::LightGray
    $area.AxisX.MajorGrid.Enabled = $false
    $area.AxisX.Interval = 1
    $chart.ChartAreas.Add($area)
    $legend = New-Object System.Windows.Forms.DataVisualization.Charting.Legend('metrics')
    $legend.Docking = 'Bottom'
    $chart.Legends.Add($legend)
    $columns = @(
        @('First draft accuracy', 'first_draft_accuracy', '#2563eb'),
        @('Final accuracy (shared validation)', 'conclusion_accuracy', '#14966e'),
        @('Task success', 'task_success_rate', '#e58a23')
    )
    foreach ($column in $columns) {
        if ($column[1] -eq 'first_draft_accuracy' -and $report.engine -ne 'ollama') { continue }
        $series = New-Object System.Windows.Forms.DataVisualization.Charting.Series($column[0])
        $series.ChartType = 'Column'
        $series.ChartArea = 'scores'
        $series.Color = [System.Drawing.ColorTranslator]::FromHtml($column[2])
        $series.IsValueShownAsLabel = $true
        $series.Label = '#VALY{0.0}%'
        foreach ($group in $report.summary) {
            $label = $group.mode + ' (n=' + $group.runs + ')'
            $pointIndex = $series.Points.AddY([double](100 * $group.($column[1])))
            $series.Points[$pointIndex].AxisLabel = $label
        }
        $chart.Series.Add($series)
    }
    $imagePath = Join-Path $ResultsDirectory 'comparison.png'
    $chart.SaveImage($imagePath, 'Png')
    Write-Output ('Saved actual evaluation chart: ' + $imagePath)
}
finally { $chart.Dispose() }
