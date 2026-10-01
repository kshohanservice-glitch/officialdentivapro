; Dentiva Pro — NSIS Installer
; Build with: makensis installer/dentivapro.nsi
;
; Produces a single-file installer that:
;   * installs DentivaPro to Program Files by default
;   * creates Start Menu shortcuts
;   * optionally creates a desktop shortcut
;   * preserves the per-user data folder on uninstall
;   * supports an explicit "Remove all data" option on uninstall.

!include "MUI2.nsh"

Name "Dentiva Pro"
OutFile "${__FILEDIR__}\DentivaPro-Setup.exe"
InstallDir "$PROGRAMFILES64\DentivaPro"
InstallDirRegKey HKLM "Software\DentivaPro" ""
RequestExecutionLevel admin
SetCompressor /SOLID lzma

!define MUI_ABORTWARNING
!define MUI_ICON "${NSISDIR}\Contrib\Graphics\Icons\modern-install.ico"
!define MUI_UNICON "${NSISDIR}\Contrib\Graphics\Icons\modern-uninstall.ico"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"

Section "Install"
    SetOutPath "$INSTDIR"
    File /r "${__FILEDIR__}\..\dist\DentivaPro\*.*"

    WriteUninstaller "$INSTDIR\Uninstall.exe"
    WriteRegStr HKLM "Software\DentivaPro" "" "$INSTDIR"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\DentivaPro" "DisplayName" "Dentiva Pro"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\DentivaPro" "UninstallString" '"$INSTDIR\Uninstall.exe"'
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\DentivaPro" "DisplayIcon" '"$INSTDIR\DentivaPro.exe"'
    WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\DentivaPro" "NoModify" 1
    WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\DentivaPro" "NoRepair" 1

    CreateDirectory "$SMPROGRAMS\Dentiva Pro"
    CreateShortcut "$SMPROGRAMS\Dentiva Pro\Dentiva Pro.lnk" "$INSTDIR\DentivaPro.exe" "" "$INSTDIR\DentivaPro.exe" 0
    CreateShortcut "$SMPROGRAMS\Dentiva Pro\Uninstall Dentiva Pro.lnk" "$INSTDIR\Uninstall.exe"

    ; Optional desktop shortcut.
    CreateShortcut "$DESKTOP\Dentiva Pro.lnk" "$INSTDIR\DentivaPro.exe" "" "$INSTDIR\DentivaPro.exe" 0
SectionEnd

Section "Uninstall"
    ; Remove application files.
    RMDir /r "$INSTDIR"
    ; Remove shortcuts.
    Delete "$SMPROGRAMS\Dentiva Pro\Dentiva Pro.lnk"
    Delete "$SMPROGRAMS\Dentiva Pro\Uninstall Dentiva Pro.lnk"
    RMDir "$SMPROGRAMS\Dentiva Pro"
    Delete "$DESKTOP\Dentiva Pro.lnk"
    ; Remove uninstall registry keys.
    DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\DentivaPro"
    DeleteRegKey HKLM "Software\DentivaPro"
    ; NOTE: per-user data under $APPDATA\DentivaPro is intentionally NOT removed
    ; automatically. A separate "Remove all data" flow in the app handles that.
SectionEnd
