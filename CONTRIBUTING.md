# Contributing to BayStateScraper

## Git Architecture & Workflow

We follow a structured branching strategy to ensure stability and continuous delivery.

### Branching Strategy

| Branch Prefix | Pattern | Purpose | CI/CD Action |
|--------------|---------|---------|--------------|
| **Production** | `main` | Production-ready code. Tagged releases only. | Deploys to Production (Stable) |
| **Development** | `develop` | Integration branch for next release. | Deploys to Staging/Dev environment |
| **Feature** | `feature/<name>` | New features. | Runs Tests & Linters |
| **Bugfix** | `fix/<issue>` | Bug fixes. | Runs Tests & Linters |
| **Release** | `release/v<x.y.z>` | Release preparation & stabilization. | Deploys to RC (Release Candidate) |
| **Hotfix** | `hotfix/<issue>` | Urgent production fixes. | Deploys to Hotfix Staging |

### Workflow Cycle

1. **Start**: Create a branch from `develop` (for features) or `main` (for hotfixes).
   ```bash
   git checkout develop
   git checkout -b feature/my-new-scraper
   ```

2. **Work**: Commit often locally.
   - Follow [Conventional Commits](https://www.conventionalcommits.org/).
   - Format: `<type>(<scope>): <description>`
   - Example: `feat(scraper): add amazon support`

3. **Verify**: Ensure local tests pass.
   ```bash
   # Run unit tests
   python -m pytest
   # Run linting
   ruff check .
   ```

4. **Push & PR**: Push to origin and open a Pull Request to `develop`.
   - CI will automatically run linting, type checking, and unit tests.
   - Code review required before merge.

5. **Merge**: Squash and merge into `develop`.

6. **Release**:
   - Create `release/vX.Y.Z` from `develop`.
   - Bump version numbers.
   - Merge `release/vX.Y.Z` into `main` and `develop`.
   - Tag `main` with `vX.Y.Z`.
   - GitHub Action triggers release build.

### Commit Messages

We enforce **Conventional Commits** to automate changelogs and versioning.

- `feat`: A new feature
- `fix`: A bug fix
- `docs`: Documentation only changes
- `style`: Changes that do not affect the meaning of the code (white-space, formatting, missing semi-colons, etc)
- `refactor`: A code change that neither fixes a bug nor adds a feature
- `perf`: A code change that improves performance
- `test`: Adding missing tests or correcting existing tests
- `chore`: Changes to the build process or auxiliary tools and libraries such as documentation generation

### CI/CD Pipelines

- **PR Validation**: Runs on all PRs.
  - Python: `pytest`, `ruff`, `mypy`
  - UI: `npm test`, `npm run lint`
  - Docker: Build verification

- **Release Pipeline**: Runs on tags `v*`.
  - Builds Docker images
  - Builds Desktop App (Tauri)
  - Publishes Release to GitHub

- **Scraper Deploy**: Runs on `push` to `main`.
  - Deploys updated scraper logic to runners.
