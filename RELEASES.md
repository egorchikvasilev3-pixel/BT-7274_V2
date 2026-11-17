# Публикация БТ-7274 на GitHub

Готовый `BT-7274_Command.exe` не хранится в репозитории: он весит около 50 МБ и публикуется в разделе **Releases**. В репозиторий попадают только исходники, документация и ресурсы.

## 1. Что нужно заранее

- GitHub Desktop установлен: `%LOCALAPPDATA%\GitHubDesktop\GitHubDesktop.exe`.
- Git из комплекта GitHub Desktop: `%LOCALAPPDATA%\GitHubDesktop\app-3.6.11\resources\app\git\cmd\git.exe`.
- Выбраны имя репозитория, лицензия и видимость (public/private).
- Собран свежий `BT-7274_Command.exe`:

```powershell
python -m pip install -r requirements.txt
python -m PyInstaller --noconfirm --clean --onefile --windowed --icon assets\Icon.ico --name BT-7274_Command launcher.py
```

## 2. Проверка перед публикацией

```powershell
git status --short
git check-ignore -v BT-7274_Command.exe
Get-FileHash BT-7274_Command.exe -Algorithm SHA256
```

В репозиторий не должны попасть:

- `BT-7274_Command.exe`, `build\`, `dist\`, `*.spec`, `__pycache__\`;
- `shots\`, `clips\`, `logs\`, `bt_voice_cache\`, `data\notes.txt`;
- `chat_history.txt`, `.bt7274.lock`, `data\shutdown.request`.

Пользовательские `helmet.webp`, `assets\Icon.ico` и исходники должны остаться.

## 3. Первый коммит

Через GitHub Desktop: **File → Add local repository** → выбрать папку проекта → **Create repository** → заполнить имя, описание и видимость → **Publish repository**.

Или через Git из GitHub Desktop (подставьте своё имя репозитория):

```powershell
$git = "$env:LOCALAPPDATA\GitHubDesktop\app-3.6.11\resources\app\git\cmd\git.exe"
& $git init -b main
& $git add .
& $git commit -m "BT-7274 V2: голосовой агент, лаунчер и управление OBS"
& $git remote add origin https://github.com/<USER>/<REPO>.git
& $git push -u origin main
```

Перед `push` убедитесь, что в `git status` нет exe и пользовательских файлов.

## 4. Выпуск релиза

1. Создайте тег версии:

```powershell
$git = "$env:LOCALAPPDATA\GitHubDesktop\app-3.6.11\resources\app\git\cmd\git.exe"
& $git tag -a v2.0.0 -m "BT-7274 V2"
& $git push origin v2.0.0
```

2. На GitHub откройте **Releases → Draft a new release**.
3. Выберите тег `v2.0.0`, название `BT-7274 V2 — голосовой титан`.
4. Прикрепите `BT-7274_Command.exe` (или zip из папки `release\`).
5. Вставьте описание из `release\RELEASE_NOTES.md` и SHA256 из `release\SHA256.txt`.
6. Опубликуйте релиз.

## 5. Шаблон описания релиза

```markdown
## БТ-7274 V2

Голосовой ИИ-комплекс для Windows: F1-рация, faster-whisper, локальная Ollama
`llama3.2:3b`, HUD-лаунчер 720×480, управление OBS Studio и голос Edge
`ru-RU-DmitryNeural`.

### Запуск

1. Скачайте `BT-7274_Command.exe`.
2. Установите OBS Studio с включённым obs-websocket (порт 4455), если нужна запись экрана.
3. Установите модель: `ollama pull llama3.2:3b`.
4. Запустите exe. Python не требуется — агент встроен в тот же файл.

### Проверка файла

SHA256: `<вставить из SHA256.txt>`
```

## 6. Обновление релиза

Для новой версии повторите сборку, проверку, коммит и создайте тег `v2.0.1` (или следующий). Старые релизы не удаляйте: пользователи смогут вернуться к рабочей версии.
