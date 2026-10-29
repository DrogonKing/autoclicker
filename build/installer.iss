; Inno Setup script for the installed build.
;
; Two things it does beyond copying files:
;   - writes a `.installed` marker next to the executable, which is how the app knows to keep its
;     profiles in %APPDATA% instead of beside the program. Without it, an installed copy would try to
;     write into Program Files, where a normal user has no permission, and profile saving would fail
;     with a confusing error.
;   - offers the per-user install by default, so no administrator prompt appears for a tool this
;     small. The user can still choose an all-users install.

; Where the one-dir PyInstaller build put its output. Overridable with /DDirBuild=...
#ifndef DirBuild
  #define DirBuild "..\dist-dir\AutoClicker"
#endif

#define AppName "AutoClicker"
#define AppVersion "1.0.10"
#define AppPublisher "drogon"
#define AppExeName "AutoClicker.exe"

[Setup]
AppId={{8E4A1C6F-2B7D-4E9A-9C31-5F0B7A2D6E44}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; per-user by default: no UAC prompt for a small utility
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
; where the setup .exe itself goes, relative to this file
OutputDir=..\dist
OutputBaseFilename=AutoClicker-{#AppVersion}-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={#AppName}
; the app is unsigned; this is stated rather than hidden
InfoBeforeFile=..\build\unsigned-notice.txt

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; The directory build's location comes in as a parameter because the workflow writes it to dist-dir/
; while an earlier version of this script read ..\dist\, and the mismatch surfaced as
; "No files found matching" during a CI build. One definition, passed in, so the two cannot disagree.
; Defaulted so a manual ISCC run still works without arguments.
Source: "{#DirBuild}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\build\installed-marker.txt"; DestDir: "{app}"; DestName: ".installed"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; profiles live outside the install directory, so they are deliberately NOT removed on uninstall:
; a user reinstalling must not lose their configuration. Their location is stated in the About panel.
Type: filesandordirs; Name: "{app}\profiles"
