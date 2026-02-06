# Pattern Discovery Report

**Date:** 2026-02-06 05:38
**Total patterns:** 64

## Statistics by Tool

| Tool | Count | % |
|------|-------|---|
| bash | 23 | 35.9% |
| grep | 10 | 15.6% |
| read | 7 | 10.9% |
| edit | 7 | 10.9% |
| ls | 5 | 7.8% |
| glob | 5 | 7.8% |
| write | 4 | 6.2% |
| find | 1 | 1.6% |
| help | 1 | 1.6% |
| unknown | 1 | 1.6% |

## Patterns by Tool

### BASH (23)

1. `^git\s+status$...`
   - Example: `git log --oneline`
2. `^git\s+diff\s*(.*)$...`
   - Example: `git log --oneline`
3. `^git\s+log\s*(.*)$...`
   - Example: `git log --oneline`
4. `^git\s+branch\s*(.*)$...`
   - Example: `git log --oneline`
5. `^git\s+add\s+(.+)$...`
   - Example: `git log --oneline`
6. `^git\s+commit\s+(.+)$...`
   - Example: `git commit`
7. `^git\s+checkout\s+(.+)$...`
   - Example: `git log --oneline`
8. `^git\s+pull\s*(.*)$...`
   - Example: `git log --oneline`
9. `^git\s+push\s*(.*)$...`
   - Example: `git log --oneline`
10. `^tree\s*(.*)$...`
   - Example: `git log --oneline`
11. `^wc\s+(?:-l\s+)?(.+)$...`
   - Example: `git log --oneline`
12. `^(?:count\s+)?lines?\s+(?:in\s+)?(.+)$...`
   - Example: `git log --oneline`
13. `^(?:размер\|size)\s+(?:файла?\s+)?(.+)$...`
   - Example: `git log --oneline`
14. `^pwd$...`
   - Example: `git log --oneline`
15. `^cd\s+(.+)$...`
   - Example: `git log --oneline`
16. `^python\s+--version$...`
   - Example: `git log --oneline`
17. `^python\s+-c\s+"?(.+)"?$...`
   - Example: `git log --oneline`
18. `^pip\s+list\s*(.*)$...`
   - Example: `git log --oneline`
19. `^pip\s+install\s+(.+)$...`
   - Example: `git log --oneline`
20. `^(?:bash\|cmd\|run\|exec)\s+(.+)$...`
   - Example: `git log --oneline`
   ... and 3 more

### EDIT (7)

1. `^in\s+(?:file\s+)?["\']?([^\s"\']+)["\']?\s+(?:rep...`
   - Example: `добавь метод test в класс Example`
2. `^(?:replace\|change)\s+["\'](.+?)["\']\s+(?:with\|to...`
   - Example: `добавь метод test в класс Example`
3. `^в\s+(?:файле\s+)?["\']?([^\s"\']+)["\']?\s+(?:зам...`
   - Example: `добавь метод test в класс Example`
4. `^(?:замени\|измени\|поменяй)\s+["\'](.+?)["\']\s+на\...`
   - Example: `добавь метод test в класс Example`
5. `^edit\s+(.+?)\s+lines?\s+(\d+)[-–](\d+)$...`
   - Example: `добавь метод test в класс Example`
6. `^edit\s+(.+?)\s+line\s+(\d+)$...`
   - Example: `добавь метод test в класс Example`
7. `^edit\s+(.+)$...`
   - Example: `добавь метод test в класс Example`

### FIND (1)

1. `^find\s+(.+)$...`
   - Example: `find`

### GLOB (5)

1. `^glob\s+"?([^"]+)"?\s*(.*)$...`
   - Example: `список файлов .js`
2. `^(?:найди\|покажи\|выведи)\s+(?:все\s+)?\.?(\w+)\s+ф...`
   - Example: `список файлов .js`
3. `^(?:список\|list)\s+(?:файлов?\s+)?\.?(\w+)\s+(?:в\...`
   - Example: `list`
4. `^(?:какие\|что за)\s+файл[ыа]?\s+(?:есть\s+)?(?:в\s...`
   - Example: `список файлов .js`
5. `^\*\.(\w+)\s+(?:files?\s+)?(?:в\|in)\s+(.+)$...`
   - Example: `files`

### GREP (10)

1. `^grep\s+"?([^"]+)"?\s+in\s+(.+)$...`
   - Example: `grep`
2. `^grep\s+"?([^"]+)"?\s*$...`
   - Example: `grep`
3. `^(?:найди\|найти\|поиск\|искать)\s+["\']([^"\']+)["\'...`
   - Example: `grep TODO`
4. `^(?:найди\|найти\|поиск\|искать)\s+["\']([^"\']+)["\'...`
   - Example: `grep TODO`
5. `^(?:покажи\|выведи)\s+(?:описания?\|документацию\|doc...`
   - Example: `grep TODO`
6. `^(?:анализ\|структура)\s+(?:модулей\|кода)\s+(?:в\s+...`
   - Example: `grep TODO`
7. `^(?:добавь\|вставь\|допиши)\s+(?:метод\|функцию)\s+(\...`
   - Example: `grep TODO`
8. `^(?:измени\|обнови\|модифицируй)\s+(?:класс\|class)\s...`
   - Example: `grep TODO`
9. `^(?:найди\|покажи\|где)\s+(?:класс\|class)\s+(\w+)...`
   - Example: `grep TODO`
10. `^(?:покажи\|найди)\s+(?:метод\|функцию\|def)\s+(\w+)(...`
   - Example: `grep TODO`

### HELP (1)

1. `^(?:help\|\?\|commands)$...`
   - Example: `help commands`

### LS (5)

1. `^ls\s*(.*)$...`
   - Example: `покажи папку src`
2. `^(?:покажи\|выведи)\s+(?:папку?\|директорию?\|содержи...`
   - Example: `покажи папку src`
3. `^список\s+(?:файлов?\|папок?\|директории?)\s*(.*)$...`
   - Example: `покажи папку src`
4. `^что\s+в\s+(?:папке\|директории)\s*(.*)$...`
   - Example: `покажи папку src`
5. `^(?:список\|покажи)\s+(?:все\s+)?модул(?:и\|ей)\s+(?...`
   - Example: `покажи папку src`

### READ (7)

1. `^read\s+(.+?)\s+lines?\s+(\d+)[-–](\d+)$...`
   - Example: `read lines`
2. `^read\s+(.+?)\s+line\s+(\d+)$...`
   - Example: `read line`
3. `^read\s+(.+)$...`
   - Example: `read`
4. `^(?:прочитай\|прочти\|покажи\|открой)\s+(?:файл\s+)?(...`
   - Example: `прочитай прочти покажи`
5. `^(?:прочитай\|прочти\|открой\|выведи)\s+(?:файл\s+)?(...`
   - Example: `прочитай прочти открой`
6. `^покажи\s+файл\s+(.+)$...`
   - Example: `покажи файл`
7. `^(?:что\s+делает\|опиши)\s+(?:модуль\|файл)\s+(.+\.p...`
   - Example: `что делает опиши`

### UNKNOWN (1)

1. `(?:add\|insert\|append\|fix\|update\|modify\|refactor\|im...`
   - Example: `add insert append`

### WRITE (4)

1. `^(?:создай\|напиши\|запиши)\s+(?:файл\s+)?([^\s:]+)\...`
   - Example: `создай напиши запиши`
2. `^(?:создай\|напиши)\s+(?:файл\s+)?([^\s]+\.py)\s+с\...`
   - Example: `напиши в output.txt`
3. `^(?:создай\|напиши)\s+(?:файл\s+)?([^\s]+\.py)\s+с\...`
   - Example: `создай напиши файл`
4. `^write\s+(.+?)\s*:\s*(.+)$...`
   - Example: `write`
