# One-command GitHub Administrator Setup

Use GitHub CLI to apply repository description, Topics, private vulnerability reporting, merge policy, and the `main` protection ruleset from one local command.

```bash
gh auth login
python scripts/github_admin_setup.py --apply
```

Run without `--apply` to preview the planned settings. The authenticated account must have repository administration permission.

The GitHub web interface is still required for pinning the repository on a personal profile and uploading a Social Preview image.
