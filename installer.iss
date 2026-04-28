; Inno Setup installer script
; 用法（由 build_installer.bat 调用）：
; ISCC /DMyAppVersion=2.3.3 /DMySourceDir="...\非压缩版\地震预警及情报实况栏 V2.3.3" /DMyOutputDir="...\installer版" installer.iss

#ifndef MyAppVersion
  #error "请通过 /DMyAppVersion=... 传入版本号"
#endif

#ifndef MySourceDir
  #error "请通过 /DMySourceDir=... 传入非压缩版源目录"
#endif

#ifndef MyOutputDir
  #define MyOutputDir "."
#endif

#ifndef MyExeName
  #error "请通过 /DMyExeName=... 传入主程序 EXE 文件名"
#endif

#ifndef MyInstalledExeName
  #define MyInstalledExeName "Rolling Subtitle.exe"
#endif

#define MyAppName "Rolling Subtitle"
#define MyAppPublisher "Mazhi"
#define MyAppVersionStr MyAppVersion

[Setup]
AppId={{C8AB6B5E-7DFD-47C1-95D8-60F2A7AABF65}
AppName={#MyAppName}
AppVersion={#MyAppVersionStr}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir={#MyOutputDir}
OutputBaseFilename=Setup_{#MyAppName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible

#ifdef MySetupIconFile
SetupIconFile={#MySetupIconFile}
#endif

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："; Flags: unchecked

[Files]
Source: "{#MySourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "{#MyExeName}"
Source: "{#MySourceDir}\{#MyExeName}"; DestDir: "{app}"; DestName: "{#MyInstalledExeName}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyInstalledExeName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyInstalledExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyInstalledExeName}"; Description: "运行 {#MyAppName}"; Flags: nowait postinstall skipifsilent
