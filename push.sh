#!/usr/bin/env sh
branch=${1:-master}
remote_names="origin github gitea"
for remote in $remote_names; do
    # get_remote=$(git remote get-url "$remote" 2>/dev/null)
    if ! get_remote=$(git remote get-url "$remote" 2>/dev/null); then
        printf "\x1b[1;33mWARN:\x1b[0m could not find remote $remote; skipping\n"
        continue
    fi
    printf "\x1b[1;34mINFO:\x1b[0m pushing $branch to $remote at $get_remote\n" &&
        git push "$remote" "$branch" &&
        printf "\x1b[1;32mINFO:\x1b[0m pushed $branch -> $remote\n" ||
        printf "\x1b[1;31mERR:\x1b[0m \x1b[31mcould not push $branch -> $remote\x1b[0m\n"
done
