"""Structure gates over ``src/``: code-shape findings that stay fixed once fixed.

Each gate names a finding class with bite evidence (``docs/tech-debt.md``, the 2026-10-01 review).
Every allow-list entry cites its finding id (the test-patch gate: ``debt #55``, or the law's own
exception, a simulated crash or race); a gate fails on a NEW site and on an entry that no longer
occurs, so the lists only shrink. The test-patch gate scans ``tests/`` instead of ``src/``.
"""

import ast
import re
from collections import Counter, defaultdict
from collections.abc import Iterator
from pathlib import Path

TESTS = Path(__file__).resolve().parent
SRC = TESTS.parent / "src"
_TREES = {
    p.relative_to(SRC).as_posix(): ast.parse(p.read_text())
    for p in sorted(SRC.rglob("*.py"))
    if "migrations" not in p.parts
}

_TEST_TREES = {
    p.relative_to(TESTS).as_posix(): ast.parse(p.read_text())
    for p in sorted(TESTS.rglob("*.py"))
    if p != Path(__file__).resolve()
}

_MIN_NODES = 12

#: Groups of functions with an identical body (sorted ``module:qualname``) -> finding id.
DUPLICATE_BODIES: dict[tuple[str, ...], str] = {}

#: The ``HX-`` request-header names belong to the request-kind owner.
HX_OWNER = "bundesarchiv/app/web/viewers.py"
#: module outside the owner -> (number of ``HX-`` header names, finding id).
HX_READS: dict[str, tuple[int, str]] = {}

_DOTTED = re.compile(r"bundesarchiv(\.\w+)+")

#: Public top-level ``module:name`` that nothing in ``src/`` references -> reason. A dotted-path
#: string (settings) counts as a reference, and Django finds a management command's ``Command``.
UNREFERENCED: dict[str, str] = {
    "bundesarchiv/app/apps.py:AppServicesConfig": "Django app config, named by INSTALLED_APPS",
    "bundesarchiv/index/apps.py:IndexConfig": "Django app config, named by INSTALLED_APPS",
    "bundesarchiv/app/push_record.py:InMemoryPushRecord": "test fake",
    "bundesarchiv/persistence/adapters/memory.py:InMemoryObjectStore": "test fake",
    "bundesarchiv/app/tasks.py:mirror_reconcile": "Procrastinate task, run by name",
    "bundesarchiv/app/tasks.py:run_worker_once_in_test": "test hook, called from tests only",
}


def _functions() -> Iterator[tuple[str, str, ast.FunctionDef | ast.AsyncFunctionDef]]:
    for module, tree in _TREES.items():
        stack: list[tuple[ast.AST, str]] = [(tree, "")]
        while stack:
            node, prefix = stack.pop()
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                    yield module, f"{prefix}{child.name}", child
                    stack.append((child, f"{prefix}{child.name}."))
                elif isinstance(child, ast.ClassDef):
                    stack.append((child, f"{prefix}{child.name}."))


def _body(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.stmt]:
    first = fn.body[0]
    is_doc = (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    )
    return fn.body[1:] if is_doc else fn.body


def _duplicate_groups() -> set[tuple[str, ...]]:
    groups = defaultdict(list)
    for module, name, fn in _functions():
        body = _body(fn)
        if sum(1 for stmt in body for _ in ast.walk(stmt)) >= _MIN_NODES:
            groups["\n".join(ast.dump(stmt) for stmt in body)].append(f"{module}:{name}")
    return {tuple(sorted(names)) for names in groups.values() if len(names) > 1}


def _assert_matches[T: (str, tuple[str, ...])](found: set[T], allowed: set[T], what: str) -> None:
    assert not found - allowed, f"new {what}: {sorted(found - allowed)}"
    assert not allowed - found, (
        f"allow-list entries that no longer occur: {sorted(allowed - found)}"
    )


def test_no_two_functions_share_a_body() -> None:
    _assert_matches(_duplicate_groups(), set(DUPLICATE_BODIES), "identical function bodies")


_HX = re.compile(r"(HTTP_)?HX[-_][\w-]+")


def _hx_reads() -> Counter[str]:
    return Counter(
        module
        for module, tree in _TREES.items()
        if module != HX_OWNER
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and _HX.fullmatch(node.value)
    )


def test_hx_header_names_appear_in_the_request_kind_owner_only() -> None:
    allowed = {module: count for module, (count, _) in HX_READS.items()}
    assert _hx_reads() == Counter(allowed), (
        f"HX- header names outside {HX_OWNER}: found {dict(_hx_reads())}, allowed {allowed}"
    )


def _referenced() -> set[str]:
    names: set[str] = set()
    for tree in _TREES.values():
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, ast.alias):
                names.add(node.name.split(".")[-1])
            elif isinstance(node, ast.Constant) and _DOTTED.fullmatch(str(node.value)):
                # a dotted path in settings (MIDDLEWARE, LOGGING, TEMPLATES) names its last part
                names.add(str(node.value).rsplit(".", 1)[-1])
    return names


def _unreferenced() -> set[str]:
    referenced = _referenced()
    return {
        f"{module}:{node.name}"
        for module, tree in _TREES.items()
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
        and not node.name.startswith("_")
        and node.name not in referenced
        and not (node.name == "Command" and "/management/commands/" in module)  # Django finds it
    }


def test_no_public_name_is_unreferenced() -> None:
    _assert_matches(
        _unreferenced(),
        set(UNREFERENCED),
        "unreferenced public names (a _ prefix exempts a module-private name; "
        "a name only Django or a test reaches goes in UNREFERENCED with its reason)",
    )


_DEBT = "debt #55"
_CRASH = "simulated crash"
_RACE = "race"

#: ``test file:test or fixture function:patched target`` -> (number of patch sites, reason). Only
#: a simulated crash or race on our own code is allowed by the law (``writer-discipline``, "Tests
#: never patch our own code"); the rest is ``docs/tech-debt.md`` #55. A patch no static read can
#: resolve counts under ``<unresolved>``.
TEST_PATCHES: dict[str, tuple[int, str]] = {
    "app/test_services.py:test_hard_delete_article_stands_when_the_remote_delete_cannot_be_enqueued:bundesarchiv.app.after_write.enqueue_mirror_delete_article": (
        1,
        _CRASH,
    ),
    "app/test_services.py:test_save_article_index_failure_stands_canonical_and_enqueues:bundesarchiv.app.after_write.index_article": (
        1,
        _CRASH,
    ),
    "app/test_services.py:test_save_article_index_failure_stands_canonical_and_enqueues:bundesarchiv.app.after_write.enqueue_reindex_article": (
        1,
        _DEBT,
    ),
    "app/test_services.py:test_save_article_swallows_enqueue_failure_after_index_failure:bundesarchiv.app.after_write.index_article": (
        1,
        _CRASH,
    ),
    "app/test_services.py:test_save_article_swallows_enqueue_failure_after_index_failure:bundesarchiv.app.after_write.enqueue_reindex_article": (
        1,
        _CRASH,
    ),
    "app/test_services.py:test_save_collection_swallows_enqueue_failure_after_index_failure:bundesarchiv.app.after_write.index_subtree": (
        1,
        _CRASH,
    ),
    "app/test_services.py:test_save_collection_swallows_enqueue_failure_after_index_failure:bundesarchiv.app.after_write.enqueue_reindex_subtree": (
        1,
        _CRASH,
    ),
    "app/test_services.py:test_save_article_gives_up_on_a_held_index_lock_and_enqueues:bundesarchiv.app.after_write.enqueue_reindex_article": (
        1,
        _DEBT,
    ),
    "app/test_services.py:test_save_article_gives_up_on_a_held_index_lock_and_enqueues:bundesarchiv.app.after_write.SYNC_LOCK_TIMEOUT_MS": (
        1,
        _DEBT,
    ),
    "app/test_services.py:test_save_article_enqueues_one_push_of_the_article:bundesarchiv.app.after_write.enqueue_mirror_push": (
        1,
        _DEBT,
    ),
    "app/test_services.py:test_delete_article_enqueues_one_push_of_the_mark:bundesarchiv.app.after_write.enqueue_mirror_push": (
        1,
        _DEBT,
    ),
    "app/test_services.py:test_hard_delete_article_enqueues_the_delete_and_no_push:bundesarchiv.app.after_write.enqueue_mirror_push": (
        1,
        _DEBT,
    ),
    "app/test_services.py:test_hard_delete_article_enqueues_the_delete_and_no_push:bundesarchiv.app.after_write.enqueue_mirror_delete_article": (
        1,
        _DEBT,
    ),
    "app/test_services.py:test_create_article_enqueues_the_push_of_the_new_article:bundesarchiv.app.after_write.enqueue_mirror_push": (
        1,
        _DEBT,
    ),
    "app/test_services.py:test_save_collection_enqueues_one_push_of_the_collection:bundesarchiv.app.after_write.enqueue_mirror_push": (
        1,
        _DEBT,
    ),
    "app/test_services.py:test_save_article_mirror_enqueue_failure_does_not_break_save:bundesarchiv.app.after_write.enqueue_mirror_push": (
        1,
        _CRASH,
    ),
    "app/test_services.py:test_save_collection_gives_up_on_a_held_index_lock_and_enqueues:bundesarchiv.app.after_write.enqueue_reindex_subtree": (
        1,
        _DEBT,
    ),
    "app/test_services.py:test_save_collection_gives_up_on_a_held_index_lock_and_enqueues:bundesarchiv.app.after_write.SYNC_LOCK_TIMEOUT_MS": (
        1,
        _DEBT,
    ),
    "app/test_services.py:test_a_rename_and_a_new_collection_leave_the_index_as_it_is:bundesarchiv.app.after_write.enqueue_reindex_subtree": (
        1,
        _DEBT,
    ),
    "app/test_services.py:test_a_rename_and_a_new_collection_leave_the_index_as_it_is:bundesarchiv.app.after_write.SYNC_LOCK_TIMEOUT_MS": (
        1,
        _DEBT,
    ),
    "app/test_services.py:test_gate_a_rename_at_a_version_it_did_not_read_still_reindexes:bundesarchiv.app.archive.Archive.collections.load": (
        2,
        _RACE,
    ),
    "app/test_tasks.py:test_reindex_article_job_recomputes_from_current_canonical:bundesarchiv.app.tasks.canonical_store": (
        1,
        _DEBT,
    ),
    "app/test_tasks.py:test_the_reconcile_job_rebuilds_everything:bundesarchiv.app.tasks.canonical_store": (
        1,
        _DEBT,
    ),
    "app/test_tasks.py:test_the_reconcile_job_logs_the_archive_stats_and_survives_their_failure:bundesarchiv.app.tasks.canonical_store": (
        1,
        _DEBT,
    ),
    "app/test_tasks.py:test_the_reconcile_job_logs_the_archive_stats_and_survives_their_failure:bundesarchiv.app.stats.log_archive_stats": (
        1,
        _CRASH,
    ),
    "app/test_tasks.py:test_reindex_subtree_job_recomputes_subtree:bundesarchiv.app.tasks.canonical_store": (
        1,
        _DEBT,
    ),
    "app/test_tasks.py:test_worker_execution_smoke_runs_deferred_reindex_article:bundesarchiv.app.tasks.canonical_store": (
        1,
        _DEBT,
    ),
    "app/test_tasks.py:test_generate_thumbnail_task_derives_from_canonical:bundesarchiv.app.tasks.canonical_store": (
        1,
        _DEBT,
    ),
    "app/test_tasks.py:test_the_push_job_pushes_the_saved_record_and_notes_it:bundesarchiv.app.tasks.canonical_store": (
        1,
        _DEBT,
    ),
    "app/test_tasks.py:test_the_push_job_pushes_the_saved_record_and_notes_it:bundesarchiv.app.tasks.mirror_store": (
        1,
        _DEBT,
    ),
    "app/test_tasks.py:test_mirror_push_task_is_noop_when_mirror_unset:bundesarchiv.app.tasks.canonical_store": (
        1,
        _DEBT,
    ),
    "app/test_tasks.py:test_mirror_push_task_is_noop_when_mirror_unset:bundesarchiv.app.tasks.mirror_store": (
        1,
        _DEBT,
    ),
    "app/test_tasks.py:test_the_reconcile_job_returns_how_many_keys_each_finding_holds:bundesarchiv.app.tasks.canonical_store": (
        1,
        _DEBT,
    ),
    "app/test_tasks.py:test_the_reconcile_job_returns_how_many_keys_each_finding_holds:bundesarchiv.app.tasks.mirror_store": (
        1,
        _DEBT,
    ),
    "app/test_tasks.py:test_mirror_reconcile_task_is_noop_when_mirror_unset:bundesarchiv.app.tasks.canonical_store": (
        1,
        _DEBT,
    ),
    "app/test_tasks.py:test_mirror_reconcile_task_is_noop_when_mirror_unset:bundesarchiv.app.tasks.mirror_store": (
        1,
        _DEBT,
    ),
    "app/test_tasks.py:test_mirror_push_worker_execution_smoke:bundesarchiv.app.tasks.canonical_store": (
        1,
        _DEBT,
    ),
    "app/test_tasks.py:test_mirror_push_worker_execution_smoke:bundesarchiv.app.tasks.mirror_store": (
        1,
        _DEBT,
    ),
    "app/test_tasks.py:test_a_hard_delete_reaches_the_system_of_record_through_the_worker:bundesarchiv.app.tasks.canonical_store": (
        1,
        _DEBT,
    ),
    "app/test_tasks.py:test_a_hard_delete_reaches_the_system_of_record_through_the_worker:bundesarchiv.app.tasks.mirror_store": (
        1,
        _DEBT,
    ),
    "app/test_tasks.py:test_the_reconcile_job_logs_one_summary_record:bundesarchiv.app.tasks.canonical_store": (
        1,
        _DEBT,
    ),
    "app/test_tasks.py:test_the_reconcile_job_logs_one_summary_record:bundesarchiv.app.tasks.mirror_store": (
        1,
        _DEBT,
    ),
    "app/test_tasks.py:test_a_failed_push_logs_its_summary_with_the_exception_class_and_still_raises:bundesarchiv.app.tasks.canonical_store": (
        1,
        _CRASH,
    ),
    "app/test_tasks.py:test_a_failed_push_logs_its_summary_with_the_exception_class_and_still_raises:bundesarchiv.app.tasks.mirror_store": (
        1,
        _DEBT,
    ),
    "app/test_thumbnails.py:test_a_request_that_waited_on_the_lock_takes_its_peers_version:bundesarchiv.app.thumbnails._derive_lock": (
        1,
        _RACE,
    ),
    "app/test_thumbnails.py:test_an_image_over_the_pixel_cap_derives_no_version:bundesarchiv.app.thumbnails._MAX_PIXELS": (
        1,
        _DEBT,
    ),
    "app/web/conftest.py:recording_store:bundesarchiv.app.archive.Archive.canonical": (1, _DEBT),
    "app/web/conftest.py:_stub_service_boundaries:bundesarchiv.app.after_write.index_article": (
        1,
        _DEBT,
    ),
    "app/web/conftest.py:_stub_service_boundaries:bundesarchiv.app.after_write.index_subtree": (
        1,
        _DEBT,
    ),
    "app/web/conftest.py:_stub_service_boundaries:bundesarchiv.app.after_write.enqueue_mirror_push": (
        1,
        _DEBT,
    ),
    "app/web/conftest.py:_stub_service_boundaries:bundesarchiv.app.after_write.enqueue_mirror_delete_article": (
        1,
        _DEBT,
    ),
    "app/web/conftest.py:_stub_service_boundaries:bundesarchiv.app.after_write.enqueue_reindex_article": (
        1,
        _DEBT,
    ),
    "app/web/conftest.py:_stub_service_boundaries:bundesarchiv.app.after_write.enqueue_reindex_subtree": (
        1,
        _DEBT,
    ),
    "app/web/conftest.py:_stub_service_boundaries:bundesarchiv.app.articles.enqueue_generate_thumbnail": (
        1,
        _DEBT,
    ),
    "app/web/test_auth_views.py:keycloak:bundesarchiv.app.web.auth_views.authorization_url": (
        1,
        _DEBT,
    ),
    "app/web/test_auth_views.py:keycloak:bundesarchiv.app.web.auth_views.fetch_tokens": (1, _DEBT),
    "app/web/test_auth_views.py:keycloak:bundesarchiv.app.web.auth_views.logout_url": (1, _DEBT),
    "app/web/test_auth_views.py:keycloak:bundesarchiv.app.web.viewers.verify_access": (1, _DEBT),
    "app/web/test_auth_views.py:keycloak:bundesarchiv.app.web.viewers.refresh": (1, _DEBT),
    "app/web/test_auth_views.py:test_callback_denies_an_expired_state_cookie:bundesarchiv.app.web.auth_views._STATE_MAX_AGE": (
        1,
        _DEBT,
    ),
    "app/web/test_bulk.py:test_apply_bulk_conflict_buckets_and_does_not_abort:bundesarchiv.app.articles.save_article": (
        1,
        _RACE,
    ),
    "app/web/test_bulk_core.py:test_apply_bulk_non_conflict_archive_error_buckets_and_does_not_abort:bundesarchiv.app.articles.save_article": (
        1,
        _CRASH,
    ),
    "app/web/test_bulk_core.py:test_apply_bulk_property_holds_across_pair_mismatch_and_archive_error:bundesarchiv.app.articles.save_article": (
        1,
        _CRASH,
    ),
    "app/web/test_bulk_views.py:test_commit_cas_race_loser_value_not_on_disk:bundesarchiv.app.articles.save_article": (
        1,
        _RACE,
    ),
    "app/web/test_catalog_actions.py:test_a_save_landing_while_the_delete_runs_survives:bundesarchiv.persistence.repository.ArticleRepository.load": (
        2,
        _RACE,
    ),
    "app/web/test_catalog_actions.py:test_a_restore_landing_while_permanent_runs_survives:bundesarchiv.persistence.repository.ArticleRepository.load": (
        2,
        _RACE,
    ),
    "app/web/test_catalog_actions.py:test_delete_with_index_lag_says_so:bundesarchiv.app.after_write.index_article": (
        1,
        _CRASH,
    ),
    "app/web/test_catalog_actions.py:test_a_save_landing_while_the_restore_runs_survives:bundesarchiv.persistence.repository.ArticleRepository.load": (
        2,
        _RACE,
    ),
    "app/web/test_catalog_actions.py:test_publish_refuses_a_record_changed_while_it_publishes:bundesarchiv.persistence.repository.ArticleRepository.load": (
        1,
        _RACE,
    ),
    "app/web/test_catalog_edit.py:test_stale_save_against_deleted_article_is_404:bundesarchiv.app.web.catalog_views._load_gated": (
        1,
        _RACE,
    ),
    "app/web/test_catalog_media.py:test_move_against_deleted_article_is_404:bundesarchiv.app.web.catalog_views._load_gated": (
        1,
        _RACE,
    ),
    "app/web/test_catalog_media.py:test_structural_save_conflict_surfaces_hinweis_not_silent:bundesarchiv.app.articles.save_article": (
        1,
        _RACE,
    ),
    "app/web/test_error_pages.py:test_an_uncaught_error_gets_the_error_page_and_repeats_nothing:bundesarchiv.app.archive.Archive.canonical": (
        1,
        _CRASH,
    ),
    "app/web/test_index_lag.py:failing_index:bundesarchiv.app.after_write.index_article": (
        1,
        _CRASH,
    ),
    "app/web/test_index_lag.py:failing_index:bundesarchiv.app.after_write.index_subtree": (
        1,
        _CRASH,
    ),
    "app/web/test_keycloak_discovery.py:test_a_token_response_without_a_refresh_token_logs_nobody_in:bundesarchiv.app.web.keycloak.verify_access": (
        1,
        _DEBT,
    ),
    "app/web/test_keycloak_discovery.py:test_a_token_response_whose_access_token_fails_the_check_logs_nobody_in:bundesarchiv.app.web.keycloak.verify_access": (
        1,
        _DEBT,
    ),
    "app/web/test_keycloak_discovery.py:_logout_realm:bundesarchiv.app.web.keycloak.refresh": (
        1,
        _DEBT,
    ),
    "app/web/test_keycloak_discovery.py:_logout_realm:bundesarchiv.app.web.keycloak._revoke": (
        1,
        _DEBT,
    ),
    "app/web/test_keycloak_tokens.py:test_a_refresh_answer_that_is_not_an_object_is_a_failed_refresh:bundesarchiv.app.web.keycloak.OAuth2Client": (
        1,
        _DEBT,
    ),
    "app/web/test_leak_matrix.py:test_route_tier_matrix:bundesarchiv.app.web.browse_views.search": (
        1,
        _DEBT,
    ),
    "app/web/test_leak_matrix.py:test_route_tier_matrix:bundesarchiv.app.web.start.facet_counts": (
        1,
        _DEBT,
    ),
    "app/web/test_leak_matrix.py:test_route_tier_matrix:bundesarchiv.app.web.start.dateless_count": (
        1,
        _DEBT,
    ),
    "app/web/test_leak_matrix.py:test_route_tier_matrix:bundesarchiv.app.web.start.search": (
        1,
        _DEBT,
    ),
    "app/web/test_media.py:test_a_failed_derive_is_the_same_404:bundesarchiv.app.thumbnails._write_atomically": (
        1,
        _CRASH,
    ),
    "app/web/test_media.py:test_authz_denies_before_any_blob_lookup:bundesarchiv.app.web.media.media_response": (
        1,
        _DEBT,
    ),
    "app/web/test_media.py:test_authz_denies_before_lookup_for_a_version:bundesarchiv.app.web.media.thumbnail_response": (
        1,
        _DEBT,
    ),
    "app/web/test_token_viewer.py:realm:bundesarchiv.app.web.viewers.verify_access": (1, _DEBT),
    "app/web/test_token_viewer.py:realm:bundesarchiv.app.web.viewers.refresh": (1, _DEBT),
    "app/web/test_viewer_of.py:test_expired_cookie_is_public:bundesarchiv.app.web.viewers._DEV_VIEWER_MAX_AGE": (
        1,
        _DEBT,
    ),
    "app/web/test_vocab.py:narrowed_vocabulary:bundesarchiv.app.web.vocab.MEDIA_TYPE_DOCUMENT_TYPES": (
        1,
        _DEBT,
    ),
    "app/web/test_workbench.py:test_pagination_second_page_via_page:bundesarchiv.app.web.browse.PAGE_SIZE": (
        1,
        _DEBT,
    ),
    "app/web/test_workbench.py:test_the_pager_holds_the_range_between_its_steps:bundesarchiv.app.web.browse.PAGE_SIZE": (
        1,
        _DEBT,
    ),
    "app/web/test_workbench.py:test_non_archivists_never_get_the_selection:bundesarchiv.app.web.browse.PAGE_SIZE": (
        1,
        _DEBT,
    ),
    "app/web/test_workbench.py:test_selection_survives_pagination_links:bundesarchiv.app.web.browse.PAGE_SIZE": (
        1,
        _DEBT,
    ),
    "app/web/test_workbench.py:test_paging_keeps_selection_mode_with_nothing_ticked:bundesarchiv.app.web.browse.PAGE_SIZE": (
        1,
        _DEBT,
    ),
    "persistence/test_localfs.py:test_commit_fsyncs_every_directory_it_creates:bundesarchiv.persistence.adapters.localfs.LocalFsObjectStore._fsync_dir": (
        1,
        _DEBT,
    ),
    "persistence/test_webdav.py:no_retry_wait:bundesarchiv.persistence.adapters.webdav._RETRY_DELAYS": (
        1,
        _DEBT,
    ),
}

_UNRESOLVED = "<unresolved>"
_PATCHERS = {"setattr", "delattr", "setitem", "delitem"}
_MOCK_PATCHERS = {
    f"{owner}.{name}"
    for owner in ("unittest.mock", "mocker")
    for name in ("patch", "patch.object", "patch.multiple", "patch.dict")
}
_PATCH_OPTIONS = {"target", "spec", "create", "spec_set", "autospec", "new_callable"}


def _dotted(expr: ast.expr, origin: dict[str, str]) -> str | None:
    """``expr`` with its root name replaced by its dotted origin, or ``None`` when it has none."""
    text = ast.unparse(expr)
    root = text.split(".")[0]
    return text.replace(root, origin[root], 1) if root in origin else None


def _names_in_scope(tree: ast.Module) -> dict[str, str]:
    """Each imported name, simple alias (``aw = after_write``) and annotated parameter -> its
    dotted origin."""
    origin: dict[str, str] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                origin[alias.asname or root] = alias.name if alias.asname else root
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for alias in node.names:
                origin[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Name | ast.Attribute)
            and (resolved := _dotted(node.value, origin))
        ):
            origin.setdefault(node.targets[0].id, resolved)
        elif (
            isinstance(node, ast.arg)
            and isinstance(node.annotation, ast.Name | ast.Attribute)
            and node.arg not in origin
            and (resolved := _dotted(node.annotation, origin))
        ):
            origin[node.arg] = resolved
    return origin


def _calls(
    node: ast.AST, scope: str = "<module>", loops: tuple[ast.For, ...] = (), cls: str = ""
) -> Iterator[tuple[ast.Call, str, tuple[ast.For, ...]]]:
    """Every call with its outermost enclosing function (``<module>`` outside one) and ``for``s."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.Call):
            yield child, scope, loops
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
            inner = f"{cls}{child.name}" if scope == "<module>" else scope
            yield from _calls(child, inner, loops, cls)
        elif isinstance(child, ast.ClassDef):
            yield from _calls(child, scope, loops, f"{cls}{child.name}.")
        else:
            yield from _calls(
                child, scope, (*loops, child) if isinstance(child, ast.For) else loops, cls
            )


def _arg(call: ast.Call, index: int, *names: str) -> ast.expr | None:
    if len(call.args) > index:
        return call.args[index]
    return next((k.value for k in call.keywords if k.arg in names), None)


def _attribute_names(
    call: ast.Call, kind: str, loops: tuple[ast.For, ...]
) -> list[str | None] | None:
    """The attributes a patch replaces on its target (``[None]``: the target itself); ``None``
    when they cannot be read."""
    if kind == "patch.multiple":
        names = [k.arg for k in call.keywords if k.arg not in _PATCH_OPTIONS]
        return None if None in names else names
    if kind not in ("setattr", "delattr", "patch.object"):
        return [None]
    name = _arg(call, 1, "name", "attribute")
    if isinstance(name, ast.Constant) and isinstance(name.value, str):
        return [name.value]
    for loop in loops:
        if (
            isinstance(name, ast.Name)
            and isinstance(loop.target, ast.Name)
            and loop.target.id == name.id
            and isinstance(loop.iter, ast.Tuple | ast.List)
            and all(
                isinstance(e, ast.Constant) and isinstance(e.value, str) for e in loop.iter.elts
            )
        ):
            return [str(e.value) for e in loop.iter.elts if isinstance(e, ast.Constant)]
    return None


def _patch_sites(call: ast.Call, origin: dict[str, str], loops: tuple[ast.For, ...]) -> list[str]:
    """The dotted ``object.attribute`` of each replacement a patch call makes, or ``<unresolved>``
    for a site no static read resolves; ``[]`` when the call is not a patcher."""
    resolved = _dotted(call.func, origin) or ast.unparse(call.func)
    if resolved in _MOCK_PATCHERS:
        kind = resolved.removeprefix("unittest.mock.").removeprefix("mocker.")
    elif isinstance(call.func, ast.Attribute) and call.func.attr in _PATCHERS:
        kind = call.func.attr
    else:
        return []
    target = _arg(call, 0, "target", "in_dict", "name")
    if isinstance(target, ast.Constant) and isinstance(target.value, str):
        base, attrs = target.value, [None]
    else:
        base = _dotted(target, origin) if target else None
        attrs = _attribute_names(call, kind, loops)
    if base is None:
        return [_UNRESOLVED]
    if attrs is None:
        return [_UNRESOLVED] if base.split(".")[0] == "bundesarchiv" else []
    return [base if a is None else f"{base}.{a}" for a in attrs]


def _test_patches() -> Counter[str]:
    return Counter(
        f"{path}:{scope}:{site}"
        for path, tree in _TEST_TREES.items()
        for origin in [_names_in_scope(tree)]
        for call, scope, loops in _calls(tree)
        for site in _patch_sites(call, origin, loops)
        if site == _UNRESOLVED or site.split(".")[0] == "bundesarchiv"
    )


def test_tests_patch_no_bundesarchiv_name_beyond_the_allow_list() -> None:
    assert all(count > 0 for count, _ in TEST_PATCHES.values()), "a zero-count TEST_PATCHES entry"
    assert {reason for _, reason in TEST_PATCHES.values()} <= {_DEBT, _CRASH, _RACE}
    found, allowed = _test_patches(), Counter({k: count for k, (count, _) in TEST_PATCHES.items()})
    assert found == allowed, (
        "tests patch our own code beyond TEST_PATCHES: assert a core's returned value, run the "
        "shell over Archive.of(InMemoryObjectStore()) and the real ORM, enqueue through "
        "tests/_queue.py (writer-discipline, 'Tests never patch our own code'). "
        f"new or changed: {dict(found - allowed)}; gone or fewer: {dict(allowed - found)}"
    )
