# Keeps the focus where it was while sclaude opens claude in a new tab.
#
# Windows Terminal selects a tab it opens, and has no switch to open one in
# the background: whoever was typing in another tab finds the rest of the word
# going into the new one. So, before wt.exe is run, this notes the selected tab
# of every Windows Terminal window and the element that has the focus, says
# "ready", and waits for a window to gain a tab; then it selects that window's
# old tab again and gives the focus back.
#
# Run by pane_focus_keep in pane.sh, through -EncodedCommand, with a first line
# setting $budget, the milliseconds sclaude still waits for "ready" when this
# process starts: a snapshot finished later was taken when sclaude had stopped
# waiting, perhaps with the new tab in it already, and the script leaves
# without acting. Counted from the process start, by this clock alone. Otherwise it gives up quietly: no window
# gaining a tab within ten seconds, or anything UI Automation refuses, leaves
# the focus where Windows Terminal put it.

Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$A = [System.Windows.Automation.AutomationElement]
$Scope = [System.Windows.Automation.TreeScope]
$Selection = [System.Windows.Automation.SelectionItemPattern]::Pattern
$windows = New-Object System.Windows.Automation.PropertyCondition($A::ClassNameProperty, 'CASCADIA_HOSTING_WINDOW_CLASS')
$tabs = New-Object System.Windows.Automation.PropertyCondition($A::ControlTypeProperty, [System.Windows.Automation.ControlType]::TabItem)

$focused = $null
try { $focused = $A::FocusedElement } catch {}
$before = @(foreach ($w in $A::RootElement.FindAll($Scope::Children, $windows)) {
  $items = @($w.FindAll($Scope::Descendants, $tabs))
  $selected = $null
  foreach ($t in $items) {
    try { if ($t.GetCurrentPattern($Selection).Current.IsSelected) { $selected = $t } } catch {}
  }
  [pscustomobject]@{ Window = $w; Count = $items.Count; Selected = $selected }
})

[Console]::Out.WriteLine('ready')
[Console]::Out.Flush()
if ($before.Count -eq 0) { exit 0 }
if (((Get-Date) - (Get-Process -Id $PID).StartTime).TotalMilliseconds -gt $budget) { exit 0 }

$until = (Get-Date).AddSeconds(10)
while ((Get-Date) -lt $until) {
  Start-Sleep -Milliseconds 50
  foreach ($b in $before) {
    try { $now = @($b.Window.FindAll($Scope::Descendants, $tabs)).Count } catch { continue }
    if ($now -le $b.Count) { continue }
    if ($b.Selected) { try { $b.Selected.GetCurrentPattern($Selection).Select() } catch {} }
    if ($focused) { try { $focused.SetFocus() } catch {} }
    exit 0
  }
}
