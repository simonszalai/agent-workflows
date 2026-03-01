---
description: Record a video walkthrough of a feature and add it to the PR description.
argument-hint: "[PR number or 'current'] [optional: base URL, default localhost:3000]"
---

# Feature Video Walkthrough

Record a video walkthrough demonstrating a feature, then add it to the PR description.

## Usage

```
/feature-video                    # Record for current branch's PR
/feature-video 847                # Record for specific PR
/feature-video 847 http://localhost:5000   # Custom base URL
/feature-video current https://staging.example.com
```

## Prerequisites

- Local development server running (check AGENTS.md for project-specific start command)
- agent-browser CLI installed
- Git repository with a PR to document
- `ffmpeg` installed (for video conversion)

## Process

### 1. Parse Arguments

- First argument: PR number or "current" (defaults to current branch's PR)
- Second argument: Base URL (defaults to `http://localhost:3000`)

```bash
# Get PR number for current branch if needed
gh pr view --json number -q '.number'
```

### 2. Gather Feature Context

```bash
gh pr view [number] --json title,body,files,headRefName -q '.'
gh pr view [number] --json files -q '.files[].path'
```

Detect the project's routing structure to map changed files to demonstrable routes:

```bash
# Check framework to determine route mapping
ls package.json 2>/dev/null && cat package.json | head -50
cat AGENTS.md 2>/dev/null | head -100
```

Identify the key routes/pages that demonstrate the feature.

### 3. Plan the Video Flow

Before recording, create a shot list:

1. **Opening shot**: Homepage or starting point (2-3 seconds)
2. **Navigation**: How user gets to the feature
3. **Feature demonstration**: Core functionality (main focus)
4. **Edge cases**: Error states, validation, etc. (if applicable)
5. **Success state**: Completed action/result

Ask user to confirm or adjust the flow:

```
Proposed Video Flow

Based on PR #[number]: [title]

1. Start at: /[starting-route]
2. Navigate to: /[feature-route]
3. Demonstrate:
   - [Action 1]
   - [Action 2]
   - [Action 3]
4. Show result: [success state]

Estimated duration: ~[X] seconds
```

Options:

1. Yes, start recording
2. Modify the flow
3. Add specific interactions

### 4. Setup Video Recording

```bash
mkdir -p tmp/videos tmp/screenshots
```

### 5. Record the Walkthrough

Execute the planned flow, capturing each step:

```bash
# Step 1: Navigate to starting point
agent-browser open "[base-url]/[start-route]"
agent-browser wait 2000
agent-browser screenshot tmp/screenshots/01-start.png

# Step 2: Navigate to feature
agent-browser snapshot -i  # Get refs
agent-browser click @e1
agent-browser wait 1000
agent-browser screenshot tmp/screenshots/02-navigate.png

# Step 3: Demonstrate feature
agent-browser snapshot -i
agent-browser click @e2
agent-browser wait 1000
agent-browser screenshot tmp/screenshots/03-feature.png

# Step 4: Capture result
agent-browser wait 2000
agent-browser screenshot tmp/screenshots/04-result.png
```

**Create video/GIF from screenshots:**

```bash
# Create MP4 video (better quality, smaller size)
# -framerate 0.5 = 2 seconds per frame
ffmpeg -y -framerate 0.5 -pattern_type glob -i 'tmp/screenshots/*.png' \
  -c:v libx264 -pix_fmt yuv420p -vf "scale=1280:-2" \
  tmp/videos/feature-demo.mp4

# Create low-quality GIF for GitHub embed (~100-200KB)
ffmpeg -y -framerate 0.5 -pattern_type glob -i 'tmp/screenshots/*.png' \
  -vf "scale=640:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=128[p];[s1][p]paletteuse" \
  -loop 0 tmp/videos/feature-demo-preview.gif
```

### 6. Upload the Video

**Option A: Upload to GitHub directly (simplest)**

Drag the GIF/video into a GitHub comment to get a hosted URL, or use the PR body editor.

**Option B: Upload to cloud storage (if configured)**

Check AGENTS.md for project-specific upload configuration (e.g., rclone, S3, R2). Example:

```bash
# Upload to configured cloud storage
# Adjust bucket/path per project configuration in AGENTS.md
rclone copy tmp/videos/ remote:bucket/pr-videos/pr-[number]/ --progress
```

**Option C: Keep local**

If no upload method is configured, reference the local path in the PR.

### 7. Update PR Description

```bash
# Get current PR body
gh pr view [number] --json body -q '.body'
```

Add video section. If the PR already has a `## Demo` section, replace it. Otherwise append:

**For GIF (embedded directly):**

```markdown
## Demo

![Feature Demo]([gif-url])
```

**For MP4 (clickable preview):**

```markdown
## Demo

[![Feature Demo]([preview-gif-url])]([video-mp4-url])

*Click to view full video*
```

```bash
gh pr edit [number] --body "[updated body with demo section]"
```

### 8. Cleanup

```bash
rm -rf tmp/screenshots
echo "Video retained at: tmp/videos/"
```

### 9. Summary

```markdown
## Feature Video Complete

**PR:** #[number] - [title]
**Video:** [url or local path]
**Duration:** ~[X] seconds

### Shots Captured
1. [Starting point]
2. [Navigation]
3. [Feature demo]
4. [Result]

### PR Updated
- [x] Demo section added to PR description
```

## Tips

- **Keep it short**: 10-30 seconds is ideal for PR demos
- **Focus on the change**: Don't include unrelated UI
- **Show before/after**: If fixing a bug, show the broken state first (if possible)
