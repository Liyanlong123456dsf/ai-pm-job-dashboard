# AI 岗位爬取 — Windows 定时任务管理器
# 用法（以管理员权限运行 PowerShell）:
#   .\schedule_manager.ps1 install   # 安装定时任务（22:00 一体化流程）
#   .\schedule_manager.ps1 uninstall # 卸载定时任务
#   .\schedule_manager.ps1 status    # 查看状态
#   .\schedule_manager.ps1 test      # 立即测试运行
#
# 流程: 22:00 登录检查 → 防休眠 → 00:00 爬取 → 完成后恢复休眠
# 轮换: 全量 → 快速 → 快速 → 循环

param([string]$Action = "help")

$TaskName = "AIPM_AutoDaily"
$ProjectDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$PythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $PythonExe) {
    $PythonExe = (Get-Command python3 -ErrorAction SilentlyContinue).Source
}
if (-not $PythonExe) {
    Write-Host "错误：未找到 Python，请确保 Python 已安装并加入 PATH" -ForegroundColor Red
    exit 1
}

switch ($Action.ToLower()) {
    "install" {
        Write-Host "📦 安装定时任务..." -ForegroundColor Cyan

        # 删除旧任务（如果存在）
        schtasks /delete /tn $TaskName /f 2>$null

        # 创建定时任务：每天 22:00 运行 auto_daily.py
        $ScriptPath = Join-Path $ProjectDir "scripts\auto_daily.py"
        $LogFile = Join-Path $ProjectDir "logs\schtask.log"

        # 确保 logs 目录存在
        $LogDir = Join-Path $ProjectDir "logs"
        if (-not (Test-Path $LogDir)) {
            New-Item -ItemType Directory -Path $LogDir | Out-Null
        }

        # 创建任务
        $TaskAction = New-ScheduledTaskAction `
            -Execute $PythonExe `
            -Argument "`"$ScriptPath`"" `
            -WorkingDirectory $ProjectDir

        $TaskTrigger = New-ScheduledTaskTrigger -Daily -At "22:00"

        $TaskSettings = New-ScheduledTaskSettingsSet `
            -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries `
            -StartWhenAvailable `
            -WakeToRun `
            -ExecutionTimeLimit (New-TimeSpan -Hours 4)

        Register-ScheduledTask `
            -TaskName $TaskName `
            -Action $TaskAction `
            -Trigger $TaskTrigger `
            -Settings $TaskSettings `
            -Description "AI PM 岗位每日自动爬取（22:00 登录检查 + 00:00 爬取）" `
            -Force

        Write-Host "✅ 已安装:" -ForegroundColor Green
        Write-Host "   • 22:00 一体化流程 ($TaskName)"
        Write-Host "     → 22:00 登录检查"
        Write-Host "     → 防休眠"
        Write-Host "     → 00:00 开始爬取"
        Write-Host "     → 完成后恢复休眠"
        Write-Host ""
        Write-Host "查看状态: .\schedule_manager.ps1 status"
    }

    "uninstall" {
        Write-Host "🗑  卸载定时任务..." -ForegroundColor Yellow
        schtasks /delete /tn $TaskName /f 2>$null
        Write-Host "✅ 已卸载定时任务: $TaskName" -ForegroundColor Green
    }

    "status" {
        Write-Host "📋 定时任务状态:" -ForegroundColor Cyan
        Write-Host ""

        # 检查任务是否存在
        $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if ($task) {
            Write-Host "--- 22:00 一体化流程 ---" -ForegroundColor White
            Write-Host "  ✅ 已安装 (状态: $($task.State))"
            $info = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction SilentlyContinue
            if ($info) {
                Write-Host "  上次运行: $($info.LastRunTime)"
                Write-Host "  下次运行: $($info.NextRunTime)"
                Write-Host "  上次结果: $($info.LastTaskResult)"
            }
        } else {
            Write-Host "--- 22:00 一体化流程 ---" -ForegroundColor White
            Write-Host "  ❌ 未安装"
        }
        Write-Host ""

        # 轮换策略
        $RotationFile = Join-Path $ProjectDir "logs\rotation_index.json"
        if (Test-Path $RotationFile) {
            Write-Host "--- 轮换策略 ---" -ForegroundColor White
            $rotation = Get-Content $RotationFile -Raw | ConvertFrom-Json
            Write-Host "  策略: $($rotation.rotation -join ' → ')"
            Write-Host "  上次: $($rotation.last_date) → $($rotation.last_mode)"
            $nextIdx = $rotation.index
            $rotArr = $rotation.rotation
            $nextMode = $rotArr[$nextIdx % $rotArr.Count]
            Write-Host "  下次: → $nextMode"
            Write-Host ""
        }

        # 最近执行记录
        $RecordFile = Join-Path $ProjectDir "logs\auto_daily_record.json"
        if (Test-Path $RecordFile) {
            Write-Host "--- 最近执行记录 ---" -ForegroundColor White
            $records = Get-Content $RecordFile -Raw | ConvertFrom-Json
            $recent = $records | Select-Object -Last 5
            foreach ($r in $recent) {
                $icon = if ($r.success) { "✅" } else { "❌" }
                $mins = [math]::Floor($r.duration_sec / 60)
                $mode = $r.mode
                $err = if ($r.error) { $r.error.Substring(0, [math]::Min(50, $r.error.Length)) } else { "" }
                Write-Host "  $icon $($r.executed_at) [$mode] ($($mins)分钟) $err"
            }
            Write-Host ""
        }

        # 登录状态
        $LoginFile = Join-Path $ProjectDir "logs\login_status.json"
        if (Test-Path $LoginFile) {
            Write-Host "--- 登录状态 ---" -ForegroundColor White
            $login = Get-Content $LoginFile -Raw | ConvertFrom-Json
            $icon = if ($login.logged_in) { "✅ 已登录" } else { "❌ 未登录" }
            Write-Host "  $icon ($($login.checked_at)) $($login.detail)"
        }
    }

    "test" {
        Write-Host "🧪 测试运行一体化流程..." -ForegroundColor Cyan
        Write-Host "⚠️  这会执行完整流程（登录检查 + 等待 + 爬取），确定吗？" -ForegroundColor Yellow
        Write-Host "   如果只想测试登录: python `"$ProjectDir\scripts\login_check.py`""
        Write-Host "   如果只想测试爬取: python `"$ProjectDir\scripts\daily_update.py`" --quick --dry-run"
        Write-Host ""
        $confirm = Read-Host "输入 y 继续"
        if ($confirm -eq "y") {
            & $PythonExe "$ProjectDir\scripts\auto_daily.py"
        }
    }

    default {
        Write-Host "用法: .\schedule_manager.ps1 {install|uninstall|status|test}" -ForegroundColor Cyan
        Write-Host ""
        Write-Host "  install   - 安装 22:00 一体化定时任务"
        Write-Host "  uninstall - 卸载定时任务"
        Write-Host "  status    - 查看当前状态、轮换策略、执行记录"
        Write-Host "  test      - 测试运行完整流程"
    }
}
