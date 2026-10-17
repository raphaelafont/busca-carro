; Instalador do Busca Carro (NSIS 3). Gerado por construir.py; não edite os caminhos à mão.
; Instala só para o usuário atual (sem pedir administrador) em %LOCALAPPDATA%\BuscaCarro.

Unicode true
Target amd64-unicode
ManifestDPIAware true
SetCompressor /SOLID lzma
SetCompressorDictSize 64
RequestExecutionLevel user

!ifndef VERSAO
  !define VERSAO "1.0.0"
!endif
!ifndef PAYLOAD
  !define PAYLOAD "payload"
!endif
!ifndef SAIDA
  !define SAIDA "BuscaCarro-Instalador.exe"
!endif

!define NOME "Busca Carro"
!define CHAVE_DESINST "Software\Microsoft\Windows\CurrentVersion\Uninstall\BuscaCarro"

Name "${NOME}"
OutFile "${SAIDA}"
InstallDir "$LOCALAPPDATA\BuscaCarro"
BrandingText "${NOME} ${VERSAO}"
ShowInstDetails nevershow
ShowUninstDetails nevershow

VIProductVersion "${VERSAO}.0"
VIFileVersion "${VERSAO}.0"
VIAddVersionKey "ProductName" "${NOME}"
VIAddVersionKey "ProductVersion" "${VERSAO}"
VIAddVersionKey "FileVersion" "${VERSAO}"
VIAddVersionKey "FileDescription" "Instalador do ${NOME}"
VIAddVersionKey "LegalCopyright" "Uso pessoal"

!include "MUI2.nsh"
!include "LogicLib.nsh"

!define MUI_ICON "icone.ico"
!define MUI_UNICON "icone.ico"
!define MUI_WELCOMEFINISHPAGE_BITMAP "lateral.bmp"
!define MUI_UNWELCOMEFINISHPAGE_BITMAP "lateral.bmp"
!define MUI_ABORTWARNING

!define MUI_WELCOMEPAGE_TITLE "Instalar o ${NOME}"
!define MUI_WELCOMEPAGE_TEXT "O ${NOME} procura carros usados na Webmotors, na OLX e no Mercado Livre e compara cada anúncio com a tabela FIPE.$\r$\n$\r$\nA instalação leva menos de um minuto e não precisa de nenhum outro programa. No final, o ícone ${NOME} aparece na área de trabalho.$\r$\n$\r$\nClique em Instalar para continuar."
!define MUI_WELCOMEPAGE_TITLE_3LINES
!define MUI_PAGE_CUSTOMFUNCTION_SHOW TextoBotaoInstalar
!insertmacro MUI_PAGE_WELCOME

!insertmacro MUI_PAGE_INSTFILES

!define MUI_FINISHPAGE_TITLE "${NOME} instalado"
!define MUI_FINISHPAGE_TEXT "O ícone ${NOME} está na área de trabalho. No painel, escolha o carro e clique em Rodar a busca."
!define MUI_FINISHPAGE_RUN "$INSTDIR\python\pythonw.exe"
!define MUI_FINISHPAGE_RUN_PARAMETERS "$\"$INSTDIR\iniciar.py$\" painel"
!define MUI_FINISHPAGE_RUN_TEXT "Abrir o ${NOME} agora"
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "PortugueseBR"

Function TextoBotaoInstalar
  ; a página de boas-vindas vai direto para a instalação: o botão "Avançar" vira "Instalar"
  GetDlgItem $0 $HWNDPARENT 1
  SendMessage $0 ${WM_SETTEXT} 0 "STR:Instalar"
FunctionEnd

Section "Instalar"
  SetShellVarContext current
  SetOutPath "$INSTDIR"

  ; encerra o painel ou uma busca em andamento de uma instalação anterior
  InitPluginsDir
  File "/oname=$PLUGINSDIR\parar.ps1" "parar.ps1"
  nsExec::Exec 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$PLUGINSDIR\parar.ps1" "$INSTDIR"'
  Pop $0

  ; programa (código antigo é substituído; config.ini, buscas.json e dados do usuário ficam).
  ; O código fica em versoes\<versão>; as atualizações automáticas acrescentam versões ali.
  RMDir /r "$INSTDIR\buscacarros"
  RMDir /r "$INSTDIR\versoes"
  RMDir /r "$INSTDIR\python"
  File /r "${PAYLOAD}\*.*"

  ; quem já usava a versão manual (pasta "Busca Carros" na área de trabalho) leva o carro e o e-mail
  ${IfNot} ${FileExists} "$INSTDIR\buscas.json"
    ${If} ${FileExists} "$DESKTOP\Busca Carros\buscas.json"
      CopyFiles /SILENT "$DESKTOP\Busca Carros\buscas.json" "$INSTDIR\buscas.json"
    ${EndIf}
  ${EndIf}
  ${IfNot} ${FileExists} "$INSTDIR\config.ini"
    ${If} ${FileExists} "$DESKTOP\Busca Carros\config.ini"
      CopyFiles /SILENT "$DESKTOP\Busca Carros\config.ini" "$INSTDIR\config.ini"
    ${Else}
      CopyFiles /SILENT "$INSTDIR\config.exemplo.ini" "$INSTDIR\config.ini"
    ${EndIf}
  ${EndIf}

  ; atalhos (o diretório de trabalho é o $OUTDIR atual)
  SetOutPath "$INSTDIR"
  CreateShortCut "$DESKTOP\${NOME}.lnk" "$INSTDIR\python\pythonw.exe" '"$INSTDIR\iniciar.py" painel' "$INSTDIR\icone.ico" 0 SW_SHOWNORMAL "" "Painel do ${NOME}"
  CreateShortCut "$SMPROGRAMS\${NOME}.lnk" "$INSTDIR\python\pythonw.exe" '"$INSTDIR\iniciar.py" painel' "$INSTDIR\icone.ico" 0 SW_SHOWNORMAL "" "Painel do ${NOME}"
  CreateShortCut "$SMSTARTUP\${NOME}.lnk" "$INSTDIR\python\pythonw.exe" '"$INSTDIR\iniciar.py" busca' "$INSTDIR\icone.ico" 0 SW_SHOWMINIMIZED "" "Busca automática do ${NOME} (a cada 2 dias)"

  ; atalhos da versão manual antiga
  Delete "$DESKTOP\Busca de carros.lnk"
  Delete "$SMSTARTUP\Busca de carros.lnk"

  ; checagem diária às 12h (Agendador de Tarefas)
  nsExec::Exec 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\agendar.ps1"'
  Pop $0

  ; desinstalador e registro em "Aplicativos instalados"
  WriteUninstaller "$INSTDIR\Desinstalar.exe"
  WriteRegStr HKCU "${CHAVE_DESINST}" "DisplayName" "${NOME}"
  WriteRegStr HKCU "${CHAVE_DESINST}" "DisplayVersion" "${VERSAO}"
  WriteRegStr HKCU "${CHAVE_DESINST}" "DisplayIcon" "$INSTDIR\icone.ico"
  WriteRegStr HKCU "${CHAVE_DESINST}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${CHAVE_DESINST}" "UninstallString" '"$INSTDIR\Desinstalar.exe"'
  WriteRegStr HKCU "${CHAVE_DESINST}" "QuietUninstallString" '"$INSTDIR\Desinstalar.exe" /S'
  WriteRegDWORD HKCU "${CHAVE_DESINST}" "NoModify" 1
  WriteRegDWORD HKCU "${CHAVE_DESINST}" "NoRepair" 1
SectionEnd

Section "Uninstall"
  SetShellVarContext current
  nsExec::Exec 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\parar.ps1" "$INSTDIR"'
  Pop $0
  nsExec::Exec 'schtasks.exe /Delete /TN "Busca Carro" /F'
  Pop $0
  Delete "$DESKTOP\${NOME}.lnk"
  Delete "$SMPROGRAMS\${NOME}.lnk"
  Delete "$SMSTARTUP\${NOME}.lnk"
  DeleteRegKey HKCU "${CHAVE_DESINST}"
  SetOutPath "$TEMP"
  RMDir /r "$INSTDIR"
SectionEnd
