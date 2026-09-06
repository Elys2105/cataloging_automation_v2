param(
    [string]$Root = "D:\DACN\JOB2\cataloging_automation_v2",
    [switch]$RunTests,
    [switch]$RunStatic,
    [switch]$IncludeLogSnippets
)

$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"

function Write-Section {
    param([string]$Title)
    "`r`n==================== $Title ====================`r`n" | Tee-Object -FilePath $script:MainLog -Append
}

function Invoke-Capture {
    param(
        [string]$Name,
        [scriptblock]$Script,
        [switch]$AppendMain
    )
    $out = Join-Path $script:ReportDir ($Name + ".txt")
    try {
        & $Script 2>&1 | Out-String -Width 5000 | Set-Content -LiteralPath $out -Encoding UTF8
        if ($AppendMain) {
            "[$Name]" | Add-Content -LiteralPath $script:MainLog -Encoding UTF8
            Get-Content -LiteralPath $out -ErrorAction SilentlyContinue | Add-Content -LiteralPath $script:MainLog -Encoding UTF8
        }
    } catch {
        "ERROR: $($_.Exception.Message)`r`n$($_ | Out-String)" | Set-Content -LiteralPath $out -Encoding UTF8
    }
}

function Test-CommandAvailable {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

if (-not (Test-Path -LiteralPath $Root)) {
    throw "Project root not found: $Root"
}

$Root = (Resolve-Path -LiteralPath $Root).Path
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$ReportDir = Join-Path $Root "runtime\audit\$stamp"
New-Item -ItemType Directory -Force -Path $ReportDir | Out-Null
$script:ReportDir = $ReportDir
$script:MainLog = Join-Path $ReportDir "00_AUDIT_SUMMARY.txt"

"CATALOGING AUTOMATION FULL PROJECT AUDIT" | Set-Content -LiteralPath $script:MainLog -Encoding UTF8
"Root: $Root" | Add-Content -LiteralPath $script:MainLog
"Audit time: $(Get-Date -Format o)" | Add-Content -LiteralPath $script:MainLog
"Machine: $env:COMPUTERNAME" | Add-Content -LiteralPath $script:MainLog
"User: $env:USERNAME" | Add-Content -LiteralPath $script:MainLog
"Read-only intent: no source files are modified; report is written only under runtime\audit." | Add-Content -LiteralPath $script:MainLog

Write-Section "A1 - ENVIRONMENT / PROCESS"

Invoke-Capture "01_processes" {
    Get-CimInstance Win32_Process |
        Where-Object {
            $_.CommandLine -and (
                $_.CommandLine -like "*cataloging_automation_v2*" -or
                $_.CommandLine -match "run_app\.py" -or
                $_.CommandLine -like "*KhoLuuTruAutomationChromeProfile*" -or
                $_.CommandLine -like "*AutomationBienMuc*"
            )
        } |
        Select-Object Name, ProcessId, ParentProcessId, ExecutablePath, CommandLine |
        Format-List
} -AppendMain

Invoke-Capture "02_os_powershell" {
    Get-ComputerInfo | Select-Object WindowsProductName, WindowsVersion, OsBuildNumber, OsArchitecture, CsSystemType
    "PowerShell: $($PSVersionTable.PSVersion)"
    "Edition: $($PSVersionTable.PSEdition)"
} -AppendMain

$venvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (Test-Path -LiteralPath $venvPython) {
    $python = $venvPython
} elseif (Test-CommandAvailable "python") {
    $python = "python"
} else {
    $python = $null
}

Invoke-Capture "03_python_info" {
    if (-not $python) { "PYTHON_NOT_FOUND"; return }
    & $python -VV
    & $python -c "import sys,platform; print('exe=',sys.executable); print('prefix=',sys.prefix); print('base_prefix=',sys.base_prefix); print('platform=',platform.platform())"
    & $python -m pip --version
} -AppendMain

Write-Section "A1 - VERSION / IMPORT PATH"

Invoke-Capture "04_project_version" {
    $pyproject = Join-Path $Root "pyproject.toml"
    $defaultYaml = Join-Path $Root "config\default.yaml"
    if (Test-Path $pyproject) {
        "--- pyproject.toml version/name ---"
        if ($python) {
            & $python -c "import pathlib,tomllib; p=pathlib.Path(r'$pyproject'); d=tomllib.loads(p.read_text(encoding='utf-8')); print('project.name=', d.get('project',{}).get('name')); print('project.version=', d.get('project',{}).get('version'))"
        } else {
            Select-String -Path $pyproject -Pattern '^\s*(name|version)\s*=' -CaseSensitive:$false
        }
    } else { "MISSING: pyproject.toml" }
    if (Test-Path $defaultYaml) {
        "--- config/default.yaml version-like keys ---"
        Select-String -Path $defaultYaml -Pattern 'version|app_version|build' -CaseSensitive:$false
    } else { "MISSING: config/default.yaml" }
} -AppendMain

Invoke-Capture "05_import_path" {
    if (-not $python) { "PYTHON_NOT_FOUND"; return }
    $env:PYTHONPATH = Join-Path $Root "src"
    $env:PYTHONNOUSERSITE = "1"
    & $python -c "import pathlib,sys; import cataloging_tool; print('cataloging_tool=', pathlib.Path(cataloging_tool.__file__).resolve()); print('sys.path='); [print('  '+x) for x in sys.path]"
} -AppendMain

Invoke-Capture "06_pip_state" {
    if (-not $python) { "PYTHON_NOT_FOUND"; return }
    & $python -m pip check
    "`n--- pip freeze ---"
    & $python -m pip freeze
    "`n--- key packages ---"
    foreach ($pkg in @('PySide6','playwright','paddleocr','paddlepaddle','PyMuPDF','opencv-python','opencv-python-headless','pytesseract','pytest','ruff','pyright','pyinstaller')) {
        "### $pkg"
        & $python -m pip show $pkg 2>$null
    }
} -AppendMain

Write-Section "A2 - REPOSITORY / ARCHITECTURE"

Invoke-Capture "07_git_state" {
    if (Test-CommandAvailable "git") {
        Set-Location $Root
        git rev-parse --show-toplevel 2>$null
        git status --short --branch 2>$null
        git log -1 --decorate --oneline 2>$null
        git rev-parse HEAD 2>$null
    } else { "git not found" }
} -AppendMain

Invoke-Capture "08_tree" {
    cmd /c ('tree /F /A "' + $Root + '"')
}

Invoke-Capture "09_file_inventory" {
    Get-ChildItem -LiteralPath $Root -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object {
            $_.FullName -notmatch '\\.venv\\' -and
            $_.FullName -notmatch '\\runtime\\audit\\' -and
            $_.FullName -notmatch '\\build\\' -and
            $_.FullName -notmatch '\\dist\\' -and
            $_.FullName -notmatch '\\__pycache__\\'
        } |
        Select-Object @{n='RelativePath';e={$_.FullName.Substring($Root.Length).TrimStart('\')}}, Length, LastWriteTime |
        Sort-Object RelativePath |
        Format-Table -AutoSize
}

Invoke-Capture "10_core_hashes" {
    $patterns = @(
        'pyproject.toml','run_app.py','config\default.yaml','config\local.yaml','rules\known_overrides.yaml',
        'src\cataloging_tool\automation\pages.py','src\cataloging_tool\workflow\runner.py',
        'src\cataloging_tool\document\parser.py','src\cataloging_tool\document\report_title.py',
        'src\cataloging_tool\document\metadata.py','src\cataloging_tool\document\pdf_pipeline.py',
        'src\cataloging_tool\document\text_extractor.py','src\cataloging_tool\document\ocr.py',
        'src\cataloging_tool\domain\models.py'
    )
    foreach ($rel in $patterns) {
        $p = Join-Path $Root $rel
        if (Test-Path -LiteralPath $p) {
            $h = Get-FileHash -Algorithm SHA256 -LiteralPath $p
            "{0}`t{1}`t{2}" -f $rel,$h.Hash,(Get-Item $p).Length
        } else {
            "MISSING`t$rel"
        }
    }
}

$rg = Test-CommandAvailable "rg"
Invoke-Capture "11_symbol_search" {
    $terms = @('DocumentListPage','DocumentEditPage','complete_and_verify','open_record','collect_records','fill_form','document_date','abstract','author','signer','security','confidence','needs_review','PaddleOCR','Tesseract','DocView','UpdateDoc','ChangeDoc','IsComplete')
    if ($rg) {
        foreach ($t in $terms) {
            "`n### $t"
            & rg -n --hidden --glob '!/.venv/**' --glob '!/runtime/audit/**' --glob '!/build/**' --glob '!/dist/**' --glob '!/__pycache__/**' -- "$t" $Root
        }
    } else {
        $files = Get-ChildItem (Join-Path $Root 'src'),(Join-Path $Root 'tests') -Recurse -File -Include *.py -ErrorAction SilentlyContinue
        foreach ($t in $terms) {
            "`n### $t"
            Select-String -Path $files.FullName -Pattern $t -SimpleMatch -ErrorAction SilentlyContinue
        }
    }
}

Invoke-Capture "12_python_ast_inventory" {
    if (-not $python) { "PYTHON_NOT_FOUND"; return }
    $env:AUDIT_ROOT = $Root
    @'
import ast, os, pathlib
root = pathlib.Path(os.environ['AUDIT_ROOT'])
for base in [root/'src', root/'tests']:
    if not base.exists():
        continue
    for p in sorted(base.rglob('*.py')):
        if '__pycache__' in p.parts:
            continue
        try:
            text=p.read_text(encoding='utf-8-sig')
            tree=ast.parse(text)
        except Exception as e:
            print(f'PARSE_ERROR\t{p.relative_to(root)}\t{e}')
            continue
        print(f'FILE\t{p.relative_to(root)}\tlines={text.count(chr(10))+1}')
        for n in ast.walk(tree):
            if isinstance(n,(ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                kind=type(n).__name__
                print(f'  {kind}\tline={getattr(n,"lineno",0)}\t{n.name}')
'@ | & $python -
}

Write-Section "A3 - BASELINE QUALITY"

Invoke-Capture "13_compileall" {
    if (-not $python) { "PYTHON_NOT_FOUND"; return }
    Set-Location $Root
    & $python -m compileall -q src tests run_app.py
    "compileall_exit=$LASTEXITCODE"
} -AppendMain

Invoke-Capture "14_pytest_collect" {
    if (-not $python) { "PYTHON_NOT_FOUND"; return }
    Set-Location $Root
    & $python -m pytest --collect-only -q
    "pytest_collect_exit=$LASTEXITCODE"
} -AppendMain

Invoke-Capture "15_pytest_markers" {
    if (-not $python) { "PYTHON_NOT_FOUND"; return }
    Set-Location $Root
    & $python -m pytest --markers
}

if ($RunTests) {
    Invoke-Capture "16_pytest_full" {
        if (-not $python) { "PYTHON_NOT_FOUND"; return }
        Set-Location $Root
        $sw = [Diagnostics.Stopwatch]::StartNew()
        & $python -m pytest -ra
        $exit=$LASTEXITCODE
        $sw.Stop()
        "pytest_exit=$exit"
        "elapsed_seconds=$([math]::Round($sw.Elapsed.TotalSeconds,3))"
    } -AppendMain
} else {
    "Full pytest was NOT executed. Re-run with -RunTests after confirming the suite cannot mutate the live website." | Add-Content -LiteralPath $script:MainLog
}

if ($RunStatic) {
    Invoke-Capture "17_ruff" {
        if (-not $python) { "PYTHON_NOT_FOUND"; return }
        Set-Location $Root
        & $python -m ruff check .
        "ruff_exit=$LASTEXITCODE"
    } -AppendMain
    Invoke-Capture "18_pyright" {
        if (-not $python) { "PYTHON_NOT_FOUND"; return }
        Set-Location $Root
        & $python -c "import pyright" 2>$null
        if ($LASTEXITCODE -eq 0) {
            & $python -m pyright
        } elseif (Test-CommandAvailable "pyright") {
            pyright
        } else {
            "pyright not installed/found"
        }
        "pyright_exit=$LASTEXITCODE"
    } -AppendMain
}

Write-Section "A4/A5 - EXISTING FIXES / ROOT CAUSE CANDIDATES"

Invoke-Capture "19_regression_keywords" {
    $patterns = @(
        'SUBMIT-001','REVIEW-001','AUTHOR-001','AUTHOR-002','AUTHOR-003',
        'intercepts pointer events','pointer events','DOM click','force=',
        'needs_review','confidence','0.82','AUTHOR_NOT_RECOVERED','required.*author','empty.*author',
        'PaddleOCR','self._engine = None','_engine=None','DocView','UpdateDoc','unknown',
        'author','issuer','office','district','ward','Binh Tien'
    )
    if ($rg) {
        foreach ($p in $patterns) {
            "`n### $p"
            & rg -n -i --hidden --glob '!/.venv/**' --glob '!/runtime/audit/**' --glob '!/build/**' --glob '!/dist/**' -- "$p" (Join-Path $Root 'src') (Join-Path $Root 'tests') (Join-Path $Root 'config') (Join-Path $Root 'rules') 2>$null
        }
    } else { "ripgrep (rg) not installed; use 11_symbol_search plus Select-String manually." }
}

Write-Section "A6 - HARDCODE / OVERRIDE AUDIT"

Invoke-Capture "20_hardcode_candidates" {
    $searchRoots = @((Join-Path $Root 'src'),(Join-Path $Root 'config'),(Join-Path $Root 'rules')) | Where-Object { Test-Path $_ }
    $patterns = @(
        'MANUAL_OVERRIDE','known_overrides','document_id\s*==','record_id\s*==','record_id\s+in',
        '\bstt\s*==','\bstt\s+in','document_number\s*==','\bnumber\s*==','\bsymbol\s*==','\babstract\s*==',
        '127385','279-CV','48-','if\s+.*[0-9]{2,}'
    )
    if ($rg) {
        foreach ($p in $patterns) {
            "`n### regex: $p"
            & rg -n -i --hidden --glob '!/.venv/**' --glob '!/runtime/**' --glob '!/tests/**' -- "$p" @searchRoots 2>$null
        }
    } else {
        "rg not found; install ripgrep or inspect rules/known_overrides.yaml and src manually."
    }
}

Invoke-Capture "21_override_files" {
    $override = Join-Path $Root 'rules\known_overrides.yaml'
    if (Test-Path -LiteralPath $override) {
        "`n===== rules\known_overrides.yaml ====="
        Get-Content -LiteralPath $override
    }
    foreach ($rel in @('config\default.yaml','config\local.yaml')) {
        $p = Join-Path $Root $rel
        if (Test-Path -LiteralPath $p) {
            $item = Get-Item -LiteralPath $p
            $hash = Get-FileHash -Algorithm SHA256 -LiteralPath $p
            "`n===== $rel (content not copied; avoids leaking credentials) ====="
            "size=$($item.Length) sha256=$($hash.Hash)"
            Select-String -Path $p -Pattern '^\s*[A-Za-z0-9_.-]+\s*:' -ErrorAction SilentlyContinue | ForEach-Object {
                if ($_.Line -match '^([ \t]*[A-Za-z0-9_.-]+\s*:).*') { $matches[1] + ' <redacted>' }
            }
        }
    }
}

Write-Section "A7 - OCR / PERFORMANCE AUDIT"

Invoke-Capture "22_ocr_dependencies" {
    if ($python) {
        @'
import importlib
mods=['paddleocr','paddle','cv2','fitz','pytesseract','PIL']
for m in mods:
    try:
        x=importlib.import_module(m)
        print(m, getattr(x,'__version__','OK'), getattr(x,'__file__',''))
    except Exception as e:
        print(m,'ERROR',repr(e))
'@ | & $python -
    }
    "`n--- Tesseract ---"
    $t = Get-Command tesseract -ErrorAction SilentlyContinue
    if ($t) {
        $t | Format-List Name,Source,Version
        tesseract --version
        tesseract --list-langs
    } else { "TESSERACT_NOT_FOUND_IN_PATH" }
    "`n--- Possible Paddle model/cache dirs ---"
    foreach ($d in @(
        (Join-Path $env:USERPROFILE '.paddleocr'),
        (Join-Path $env:USERPROFILE '.paddlex'),
        (Join-Path $env:LOCALAPPDATA 'paddleocr'),
        (Join-Path $Root 'models'),
        (Join-Path $Root 'runtime\models')
    )) {
        if ($d -and (Test-Path $d)) { Get-ChildItem $d -Recurse -File -ErrorAction SilentlyContinue | Select-Object FullName,Length,LastWriteTime }
    }
}

Invoke-Capture "23_ocr_code_paths" {
    $patterns = @('PaddleOCR\(','self\._engine','_engine\s*=\s*None','Tesseract','pytesseract','psm','crop','white_ratio','contrast','edge','cache','checksum','bbox','confidence','text layer','get_text','page.get_text')
    if ($rg) {
        foreach ($p in $patterns) {
            "`n### $p"
            & rg -n -i -- "$p" (Join-Path $Root 'src') 2>$null
        }
    }
}

Write-Section "A8 - PACKAGING / INSTALLER STATUS"

Invoke-Capture "24_packaging_inventory" {
    Get-ChildItem -LiteralPath $Root -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object {
            $_.FullName -notmatch '\\.venv\\' -and
            ($_.Extension -in '.spec','.iss','.ico','.manifest','.ps1','.bat','.cmd' -or $_.Name -match 'pyinstaller|installer|package|build|release|setup')
        } |
        Select-Object FullName,Length,LastWriteTime |
        Sort-Object FullName |
        Format-Table -AutoSize
}

Invoke-Capture "25_packaging_code_refs" {
    $patterns = @('PyInstaller','sys\._MEIPASS','importlib\.resources','Program Files','LOCALAPPDATA','APPDATA','runtime','Chrome','channel\s*=.*chrome','executable_path','playwright install','TESSDATA_PREFIX','tesseract_cmd','paddleocr','model_dir','version')
    if ($rg) {
        foreach ($p in $patterns) {
            "`n### $p"
            & rg -n -i --hidden --glob '!/.venv/**' --glob '!/runtime/audit/**' -- "$p" $Root 2>$null
        }
    }
}

Invoke-Capture "26_external_tools" {
    "--- Chrome candidates ---"
    foreach ($p in @(
        "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
        "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
        "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
    )) {
        if ($p -and (Test-Path $p)) {
            $vi = (Get-Item -LiteralPath $p).VersionInfo
            "$p`tFileVersion=$($vi.FileVersion)`tProductVersion=$($vi.ProductVersion)"
        }
    }
    "`n--- Inno Setup candidates ---"
    foreach ($p in @(
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
    )) { if ($p -and (Test-Path $p)) { $p } }
}

Write-Section "A9 - SLOT / RUNTIME ISOLATION"

Invoke-Capture "27_runtime_layout" {
    $runtime = Join-Path $Root 'runtime'
    if (Test-Path $runtime) {
        "===== runtime summary (document filenames/content omitted) ====="
        Get-ChildItem $runtime -Directory -ErrorAction SilentlyContinue | ForEach-Object {
            $files = Get-ChildItem $_.FullName -Recurse -File -ErrorAction SilentlyContinue
            $bytes = ($files | Measure-Object Length -Sum).Sum
            if ($null -eq $bytes) { $bytes = 0 }
            "{0}`tfiles={1}`tbytes={2}" -f $_.Name,$files.Count,$bytes
            $files | Group-Object Extension | Sort-Object Count -Descending | Select-Object -First 10 | ForEach-Object {
                "    ext={0}`tcount={1}" -f $_.Name,$_.Count
            }
        }
    }
    foreach ($dir in @('config','scripts','installer')) {
        $p = Join-Path $Root $dir
        if (Test-Path $p) {
            "`n===== $dir ====="
            Get-ChildItem $p -Recurse -Depth 4 -ErrorAction SilentlyContinue |
                Select-Object @{n='RelativePath';e={$_.FullName.Substring($Root.Length).TrimStart('\')}},PSIsContainer,Length,LastWriteTime |
                Format-Table -AutoSize
        }
    }
}

Invoke-Capture "28_slot_profile_refs" {
    $patterns = @('slot1','slot2','profile','user-data-dir','KhoLuuTruAutomationChromeProfile','runtime','database','sqlite','cache','downloads','artifacts','job state','lock','mutex','filelock')
    if ($rg) {
        foreach ($p in $patterns) {
            "`n### $p"
            & rg -n -i -- "$p" (Join-Path $Root 'src') (Join-Path $Root 'config') (Join-Path $Root 'scripts') 2>$null
        }
    }
}

Invoke-Capture "29_database_schema" {
    if (-not $python) { "PYTHON_NOT_FOUND"; return }
    $env:AUDIT_ROOT = $Root
    @'
import pathlib, sqlite3, os
root=pathlib.Path(os.environ['AUDIT_ROOT'])
for p in sorted(root.rglob('*')):
    if not p.is_file() or p.suffix.lower() not in {'.db','.sqlite','.sqlite3'}:
        continue
    if 'runtime\\audit' in str(p).lower():
        continue
    print('\nDB', p.relative_to(root))
    try:
        uri='file:'+p.as_posix()+'?mode=ro'
        con=sqlite3.connect(uri, uri=True, timeout=1)
        for name,typ,sql in con.execute("select name,type,sql from sqlite_master where type in ('table','index','view') order by type,name"):
            print(typ, name, sql or '')
        con.close()
    except Exception as e:
        print('ERROR', repr(e))
'@ | & $python -
}

if ($IncludeLogSnippets) {
    Invoke-Capture "30_log_error_snippets" {
        $logRoot = Join-Path $Root 'runtime\logs'
        if (-not (Test-Path $logRoot)) { "NO_RUNTIME_LOGS"; return }
        $patterns = 'Traceback|ERROR|Exception|Timeout|intercepts pointer|AUTHOR|PaddleOCR|needs_review|confidence|browser executable|DocView|UpdateDoc|submission_uncertain|required.*author|empty.*author'
        if ($rg) {
            & rg -n -i -C 2 -- "$patterns" $logRoot
        } else {
            Get-ChildItem $logRoot -Recurse -File | Select-String -Pattern $patterns -CaseSensitive:$false -Context 2,2
        }
    }
}

Write-Section "FINAL - REPORT LOCATION"
"Audit report: $ReportDir" | Add-Content -LiteralPath $script:MainLog

$zip = Join-Path (Split-Path $ReportDir -Parent) ("audit_" + $stamp + ".zip")
try {
    Compress-Archive -Path (Join-Path $ReportDir '*') -DestinationPath $zip -Force
    "ZIP: $zip" | Add-Content -LiteralPath $script:MainLog
} catch {
    "ZIP_FAILED: $($_.Exception.Message)" | Add-Content -LiteralPath $script:MainLog
}

Write-Host ""
Write-Host "AUDIT COMPLETE" -ForegroundColor Green
Write-Host "Summary: $script:MainLog"
Write-Host "Report : $ReportDir"
if (Test-Path $zip) { Write-Host "ZIP    : $zip" }
Write-Host ""
Write-Host "IMPORTANT: Full pytest is only run when -RunTests is supplied." -ForegroundColor Yellow
Write-Host "Use -RunStatic to execute Ruff/Pyright. Use -IncludeLogSnippets only if local logs may be included in the audit bundle." -ForegroundColor Yellow
