# telesma/state/PLAN.md - Example TODO application

## Project information

- **Name**: todo-api
- **Stack**: Python 3.11, FastAPI, SQLite, pytest

## Tasks

### Phase 1: Project setup

- [ ] Task 1.1: Create the directory structure: src/, tests/, requirements.txt
- [ ] Task 1.2: Set up FastAPI in src/main.py with a GET /health endpoint
- [ ] Task 1.3: Configure pytest in pytest.ini
- [ ] Test 1: the /health endpoint returns {"status": "ok"} (requires: 1.2, 1.3)

### Phase 2: Model and database

- [ ] Task 2.1: Create the Todo model in src/models.py (id, title, completed, created_at) (requires: 1.1)
- [ ] Test 2.1: creating a Todo instance with valid fields (requires: 2.1)
- [ ] Task 2.2: Set up SQLite with SQLAlchemy in src/database.py (requires: 1.1)
- [ ] Test 2.2: connecting to the database and creating the table (requires: 2.2)

### Phase 3: Create TODO endpoint

- [ ] Task 3.1: POST /todos endpoint - create a new todo (requires: 2.1, 2.2)
- [ ] Test 3.1a: POST /todos creates a new record and returns 201 (requires: 3.1)
- [ ] Test 3.1b: POST /todos without a title returns 422 (requires: 3.1)

### Phase 4: List TODO endpoint

- [ ] Task 4.1: GET /todos endpoint - list of all todos (requires: 2.1, 2.2)
- [ ] Test 4.1a: GET /todos returns a list (empty when there are no records) (requires: 4.1)
- [ ] Test 4.1b: GET /todos returns the created todo (requires: 4.1, 3.1)

### Phase 5: TODO details endpoint

- [ ] Task 5.1: GET /todos/{id} endpoint - details of a single todo (requires: 2.1, 2.2)
- [ ] Test 5.1a: GET /todos/{id} returns the right todo (requires: 5.1)
- [ ] Test 5.1b: GET /todos/{id} for a non-existent one returns 404 (requires: 5.1)

### Phase 6: Updating and deleting TODOs

- [ ] Task 6.1: PUT /todos/{id} endpoint - update a todo (requires: 5.1)
- [ ] Test 6.1: PUT /todos/{id} updates title and completed (requires: 6.1)
- [ ] Task 6.2: DELETE /todos/{id} endpoint - delete a todo (requires: 5.1)
- [ ] Test 6.2: DELETE /todos/{id} deletes the record and returns 204 (requires: 6.2)

### Phase 7: Documentation

- [ ] Task 7.1: Add docstrings to the functions in main.py (requires: 6.1, 6.2)
- [ ] Task 7.2: Create README.md with instructions on how to run it (requires: 7.1)

## Notes

- Dependencies: `(requires: X.X)` - Telesma skips the task if a dependency is not completed
- We use SQLite for simplicity (file: todos.db)
- FastAPI generates /docs with Swagger UI automatically
- Tests use a separate in-memory database
- Every endpoint has a test right after its implementation
