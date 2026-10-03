import os
import unittest
import uuid

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from brandpilot.database import build_engine


DATABASE_URL = os.getenv("BRANDPILOT_TEST_DATABASE_URL")


@unittest.skipUnless(DATABASE_URL, "BRANDPILOT_TEST_DATABASE_URL is not configured")
class PostgresRlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", DATABASE_URL.replace("%", "%%"))
        command.upgrade(config, "head")

    def setUp(self):
        self.engine = create_engine(DATABASE_URL, pool_size=1, max_overflow=0)
        self.app_engine = build_engine(DATABASE_URL, role="brandpilot_app")
        self.workspace_a = str(uuid.uuid4())
        self.workspace_b = str(uuid.uuid4())
        self.user_a = str(uuid.uuid4())
        self.user_b = str(uuid.uuid4())
        self.job_a = str(uuid.uuid4())
        self.job_b = str(uuid.uuid4())
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id,email,password_hash,created_at) "
                    "VALUES (:a,:a_email,'fixture',now()),(:b,:b_email,'fixture',now())"
                ),
                {
                    "a": self.user_a,
                    "b": self.user_b,
                    "a_email": f"rls-a-{self.user_a}@example.test",
                    "b_email": f"rls-b-{self.user_b}@example.test",
                },
            )
            connection.execute(
                text(
                    "INSERT INTO workspaces "
                    "(id,name,language,timezone,currency,data_mode,selected_provider,created_at) "
                    "VALUES (:a,'Nile Studio Cairo','ar-EG','Africa/Cairo','EGP','offline_test','none',now()),"
                    "(:b,'Nile Studios Cairo','ar-EG','Africa/Cairo','EGP','offline_test','none',now())"
                ),
                {"a": self.workspace_a, "b": self.workspace_b},
            )
            for job_id, workspace_id, key in (
                (self.job_a, self.workspace_a, f"rls-a-{uuid.uuid4()}"),
                (self.job_b, self.workspace_b, f"rls-b-{uuid.uuid4()}"),
            ):
                connection.execute(
                    text(
                        "INSERT INTO jobs "
                        "(id,workspace_id,kind,payload,status,dedupe_key,attempts,max_attempts,"
                        "available_at,checkpoint,created_at,updated_at) "
                        "VALUES (:id,:workspace,'fixture.artifact','{}','queued',:key,0,3,now(),'{}',now(),now())"
                    ),
                    {"id": job_id, "workspace": workspace_id, "key": key},
                )
            for workspace_id, job_id, user_id, key in (
                (self.workspace_a, self.job_a, self.user_a, "agent-a"),
                (self.workspace_b, self.job_b, self.user_b, "agent-b"),
            ):
                connection.execute(
                    text(
                        "INSERT INTO agent_runs (id,workspace_id,job_id,created_by_user_id,dedupe_key,provider,model,status,prompt_classification,redacted_prompt,output,checkpoint,cancel_requested,created_at,updated_at) "
                        "VALUES (:id,:workspace,:job,:user,:key,'gemini','fixture','queued','{}','public','{}','{}',false,now(),now())"
                    ),
                    {"id": str(uuid.uuid4()), "workspace": workspace_id, "job": job_id, "user": user_id, "key": f"{key}-{uuid.uuid4()}"},
                )

    def tearDown(self):
        with self.engine.begin() as connection:
            connection.execute(
                text("DELETE FROM workspaces WHERE id IN (:a, :b)"),
                {"a": self.workspace_a, "b": self.workspace_b},
            )
            connection.execute(text("DELETE FROM users WHERE id IN (:a, :b)"), {"a": self.user_a, "b": self.user_b})
        self.engine.dispose()
        self.app_engine.dispose()

    def _visible_jobs(self, workspace_id: str) -> tuple[str, list[str]]:
        with self.app_engine.begin() as connection:
            role = connection.scalar(text("SELECT current_user"))
            connection.execute(
                text("SELECT set_config('app.workspace_id', :workspace, true)"),
                {"workspace": workspace_id},
            )
            rows = connection.execute(text("SELECT id FROM jobs ORDER BY id")).scalars().all()
            return role, list(rows)

    def test_actual_application_role_isolates_reused_pool_connection(self):
        role_a, visible_a = self._visible_jobs(self.workspace_a)
        role_b, visible_b = self._visible_jobs(self.workspace_b)
        self.assertEqual(role_a, "brandpilot_app")
        self.assertEqual(role_b, "brandpilot_app")
        self.assertEqual(visible_a, [self.job_a])
        self.assertEqual(visible_b, [self.job_b])

    def test_creative_versions_and_renders_follow_workspace_rls(self):
        plan_a, plan_b = str(uuid.uuid4()), str(uuid.uuid4())
        design_a, design_b = str(uuid.uuid4()), str(uuid.uuid4())
        with self.engine.begin() as connection:
            for workspace, user, plan, design in (
                (self.workspace_a, self.user_a, plan_a, design_a),
                (self.workspace_b, self.user_b, plan_b, design_b),
            ):
                connection.execute(text(
                    "INSERT INTO weekly_plans (id,workspace_id,week_start,revision,status,profile_version,strategy,items,created_by_user_id,created_at) "
                    "VALUES (:plan,:workspace,'2026-12-28',1,'draft',1,'{}','[]',:user,now())"
                ), {"plan": plan, "workspace": workspace, "user": user})
                connection.execute(text(
                    "INSERT INTO design_versions (id,workspace_id,plan_id,item_id,revision,scene,caption,factual_refs,needs_fact_review,created_by_user_id,created_at) "
                    "VALUES (:design,:workspace,:plan,:item,1,'{}','caption','[]',false,:user,now())"
                ), {"design": design, "workspace": workspace, "plan": plan, "item": str(uuid.uuid4()), "user": user})
                connection.execute(text(
                    "INSERT INTO render_artifacts (id,workspace_id,design_version_id,slide_id,preset,storage_key,sha256,width,height,created_at) "
                    "VALUES (:id,:workspace,:design,:slide,'square',:key,:sha,1080,1080,now())"
                ), {"id": str(uuid.uuid4()), "workspace": workspace, "design": design,
                    "slide": str(uuid.uuid4()), "key": f"workspaces/{workspace}/fixture.png", "sha": "0" * 64})
        for workspace, own_design in ((self.workspace_a, design_a), (self.workspace_b, design_b)):
            with self.app_engine.begin() as connection:
                connection.execute(text("SELECT set_config('app.workspace_id', :workspace, true)"), {"workspace": workspace})
                visible = connection.execute(text("SELECT id FROM design_versions ORDER BY id")).scalars().all()
                rendered = connection.execute(text("SELECT design_version_id FROM render_artifacts")).scalars().all()
                self.assertEqual(visible, [own_design])
                self.assertEqual(rendered, [own_design])
        with self.assertRaises(Exception):
            with self.app_engine.begin() as connection:
                connection.execute(text("SELECT set_config('app.workspace_id', :workspace, true)"), {"workspace": self.workspace_a})
                connection.execute(text(
                    "INSERT INTO design_versions (id,workspace_id,plan_id,item_id,revision,scene,caption,factual_refs,needs_fact_review,created_by_user_id,created_at) "
                    "VALUES (:id,:workspace,:foreign_plan,:item,1,'{}','x','[]',false,:user,now())"
                ), {"id": str(uuid.uuid4()), "workspace": self.workspace_a, "foreign_plan": plan_b,
                    "item": str(uuid.uuid4()), "user": self.user_a})

    def test_feedback_and_learning_follow_workspace_rls(self):
        with self.engine.begin() as connection:
            for workspace, user in ((self.workspace_a, self.user_a), (self.workspace_b, self.user_b)):
                plan, design, feedback = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
                connection.execute(text(
                    "INSERT INTO weekly_plans (id,workspace_id,week_start,revision,status,profile_version,strategy,items,created_by_user_id,created_at) "
                    "VALUES (:plan,:workspace,'2026-12-28',1,'draft',1,'{}','[]',:user,now())"
                ), {"plan": plan, "workspace": workspace, "user": user})
                connection.execute(text(
                    "INSERT INTO design_versions (id,workspace_id,plan_id,item_id,revision,scene,caption,factual_refs,needs_fact_review,created_by_user_id,created_at) "
                    "VALUES (:design,:workspace,:plan,:item,1,'{}','caption','[]',false,:user,now())"
                ), {"design": design, "workspace": workspace, "plan": plan,
                    "item": str(uuid.uuid4()), "user": user})
                connection.execute(text(
                    "INSERT INTO design_feedback (id,workspace_id,design_version_id,original_text,interpretation,category,kind,scope,scope_key,status,created_by_user_id,created_at) "
                    "VALUES (:feedback,:workspace,:design,'original','shorter copy','copy','preference','future','*','approved',:user,now())"
                ), {"feedback": feedback, "workspace": workspace, "design": design, "user": user})
                connection.execute(text(
                    "INSERT INTO learned_preferences (id,workspace_id,feedback_id,scope,scope_key,category,instruction,version,status,approved_by_user_id,created_at) "
                    "VALUES (:id,:workspace,:feedback,'future','*','copy','shorter copy',1,'active',:user,now())"
                ), {"id": str(uuid.uuid4()), "workspace": workspace, "feedback": feedback, "user": user})
        for workspace in (self.workspace_a, self.workspace_b):
            with self.app_engine.begin() as connection:
                connection.execute(text("SELECT set_config('app.workspace_id', :workspace, true)"), {"workspace": workspace})
                for table in ("design_feedback", "learned_preferences"):
                    self.assertEqual(connection.execute(text(f"SELECT workspace_id FROM {table}")).scalars().all(),
                                     [workspace])
        with self.assertRaises(Exception):
            with self.app_engine.begin() as connection:
                connection.execute(text("SELECT set_config('app.workspace_id', :workspace, true)"),
                                   {"workspace": self.workspace_a})
                connection.execute(text(
                    "UPDATE learned_preferences SET workspace_id = :foreign WHERE workspace_id = :own"
                ), {"foreign": self.workspace_b, "own": self.workspace_a})

    def test_publication_approvals_and_attempts_follow_workspace_rls(self):
        with self.engine.begin() as connection:
            for workspace, user in ((self.workspace_a, self.user_a), (self.workspace_b, self.user_b)):
                plan, design, approval = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
                connection.execute(text(
                    "INSERT INTO weekly_plans (id,workspace_id,week_start,revision,status,profile_version,strategy,items,created_by_user_id,created_at) "
                    "VALUES (:plan,:workspace,'2030-01-01',1,'approved',1,'{}','[]',:user,now())"
                ), {"plan": plan, "workspace": workspace, "user": user})
                connection.execute(text(
                    "INSERT INTO design_versions (id,workspace_id,plan_id,item_id,revision,scene,caption,factual_refs,needs_fact_review,created_by_user_id,created_at) "
                    "VALUES (:design,:workspace,:plan,:item,1,'{}','caption','[]',false,:user,now())"
                ), {"design": design, "workspace": workspace, "plan": plan,
                    "item": str(uuid.uuid4()), "user": user})
                connection.execute(text(
                    "INSERT INTO publication_approvals "
                    "(id,workspace_id,design_version_id,destination_platform,destination_account_id,scheduled_at_utc,"
                    "schedule_local,schedule_fold,timezone_name,content_hash,source_snapshot,idempotency_key,"
                    "delivery_mode,status,approved_by_user_id,approved_at) "
                    "VALUES (:approval,:workspace,:design,'facebook_pages','Page',now() + interval '1 day',"
                    "'2030-01-01T12:00',0,'Africa/Cairo',:hash,'{}',:key,'manual','approved',:user,now())"
                ), {"approval": approval, "workspace": workspace, "design": design,
                    "hash": "a" * 64, "key": str(uuid.uuid4()), "user": user})
                connection.execute(text(
                    "INSERT INTO publication_attempts (id,workspace_id,approval_id,status,created_at,updated_at) "
                    "VALUES (:id,:workspace,:approval,'manual_ready',now(),now())"
                ), {"id": str(uuid.uuid4()), "workspace": workspace, "approval": approval})
        for workspace in (self.workspace_a, self.workspace_b):
            with self.app_engine.begin() as connection:
                connection.execute(text("SELECT set_config('app.workspace_id', :workspace, true)"), {"workspace": workspace})
                for table in ("publication_approvals", "publication_attempts"):
                    self.assertEqual(connection.execute(text(f"SELECT workspace_id FROM {table}")).scalars().all(),
                                     [workspace])
        with self.assertRaises(Exception):
            with self.app_engine.begin() as connection:
                connection.execute(text("SELECT set_config('app.workspace_id', :workspace, true)"),
                                   {"workspace": self.workspace_a})
                connection.execute(text(
                    "UPDATE publication_attempts SET workspace_id = :foreign WHERE workspace_id = :own"
                ), {"foreign": self.workspace_b, "own": self.workspace_a})

    def test_rls_rejects_cross_workspace_insert(self):
        with self.assertRaises(Exception):
            with self.app_engine.begin() as connection:
                connection.execute(
                    text("SELECT set_config('app.workspace_id', :workspace, true)"),
                    {"workspace": self.workspace_a},
                )
                connection.execute(
                    text(
                        "INSERT INTO jobs "
                        "(id,workspace_id,kind,payload,status,dedupe_key,attempts,max_attempts,"
                        "available_at,checkpoint,created_at,updated_at) "
                        "VALUES (:id,:workspace,'fixture.artifact','{}','queued',:key,0,3,now(),'{}',now(),now())"
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "workspace": self.workspace_b,
                        "key": f"forged-{uuid.uuid4()}",
                    },
                )

    def test_phase4_agent_runs_follow_the_same_workspace_policy(self):
        with self.app_engine.begin() as connection:
            connection.execute(
                text("SELECT set_config('app.workspace_id', :workspace, true)"),
                {"workspace": self.workspace_a},
            )
            visible = connection.execute(
                text("SELECT workspace_id FROM agent_runs ORDER BY workspace_id")
            ).scalars().all()
        self.assertEqual(visible, [self.workspace_a])

    def test_phase5_social_posts_are_isolated_and_cross_workspace_insert_fails(self):
        with self.engine.begin() as connection:
            for workspace_id, suffix in ((self.workspace_a, "a"), (self.workspace_b, "b")):
                connection.execute(
                    text(
                        "INSERT INTO social_connections "
                        "(id,workspace_id,provider,authorized_by_user_id,status,granted_scopes,capabilities,created_at,updated_at) "
                        "VALUES (:id,:workspace,'meta',:user,'disconnected','[]','{}',now(),now())"
                    ),
                    {
                        "id": str(uuid.uuid4()), "workspace": workspace_id,
                        "user": self.user_a if suffix == "a" else self.user_b,
                    },
                )
                connection.execute(
                    text(
                        "INSERT INTO social_posts "
                        "(id,workspace_id,provider,account_id,source_id,text,provenance,observed_at) "
                        "VALUES (:id,:workspace,'instagram',:account,:source,'post','owner_imported',now())"
                    ),
                    {
                        "id": str(uuid.uuid4()), "workspace": workspace_id,
                        "account": f"account-{suffix}", "source": f"post-{suffix}",
                    },
                )
        with self.app_engine.begin() as connection:
            connection.execute(
                text("SELECT set_config('app.workspace_id', :workspace, true)"),
                {"workspace": self.workspace_a},
            )
            visible = connection.execute(text("SELECT source_id FROM social_posts")).scalars().all()
            connections = connection.execute(text("SELECT workspace_id FROM social_connections")).scalars().all()
        self.assertEqual(visible, ["post-a"])
        self.assertEqual(connections, [self.workspace_a])
        with self.assertRaises(Exception):
            with self.app_engine.begin() as connection:
                connection.execute(
                    text("SELECT set_config('app.workspace_id', :workspace, true)"),
                    {"workspace": self.workspace_a},
                )
                connection.execute(
                    text(
                        "INSERT INTO social_posts "
                        "(id,workspace_id,provider,account_id,source_id,text,provenance,observed_at) "
                        "VALUES (:id,:workspace,'instagram','forged','forged','post','owner_imported',now())"
                    ),
                    {"id": str(uuid.uuid4()), "workspace": self.workspace_b},
                )

    def test_phase6_observations_follow_workspace_rls_and_post_fk(self):
        post_a, post_b = str(uuid.uuid4()), str(uuid.uuid4())
        with self.engine.begin() as connection:
            for workspace, post_id in ((self.workspace_a, post_a), (self.workspace_b, post_b)):
                connection.execute(text(
                    "INSERT INTO social_posts (id,workspace_id,provider,account_id,source_id,text,provenance,observed_at) "
                    "VALUES (:id,:workspace,'instagram','account',:id,'post','owner_imported',now())"
                ), {"id": post_id, "workspace": workspace})
                connection.execute(text(
                    "INSERT INTO metric_observations "
                    "(id,workspace_id,post_id,metric,traffic,status,value,window_start,window_end,source_ref,observed_at) "
                    "VALUES (:id,:workspace,:post,'reactions','organic','observed',1,now()-interval '2 days',now()-interval '1 day','fixture',now())"
                ), {"id": str(uuid.uuid4()), "workspace": workspace, "post": post_id})
                connection.execute(text(
                    "INSERT INTO audit_comments (id,workspace_id,post_id,redacted_text,source_ref,observed_at) "
                    "VALUES (:id,:workspace,:post,'price?',:id,now())"
                ), {"id": str(uuid.uuid4()), "workspace": workspace, "post": post_id})
        with self.app_engine.begin() as connection:
            connection.execute(text("SELECT set_config('app.workspace_id', :workspace, true)"), {"workspace": self.workspace_a})
            metrics = connection.execute(text("SELECT post_id FROM metric_observations")).scalars().all()
            comments = connection.execute(text("SELECT post_id FROM audit_comments")).scalars().all()
        self.assertEqual(metrics, [post_a])
        self.assertEqual(comments, [post_a])
        with self.assertRaises(Exception):
            with self.app_engine.begin() as connection:
                connection.execute(text("SELECT set_config('app.workspace_id', :workspace, true)"), {"workspace": self.workspace_a})
                connection.execute(text(
                    "INSERT INTO audit_comments (id,workspace_id,post_id,redacted_text,source_ref,observed_at) "
                    "VALUES (:id,:workspace,:post,'forged',:id,now())"
                ), {"id": str(uuid.uuid4()), "workspace": self.workspace_b, "post": post_b})
        with self.assertRaises(Exception):
            with self.app_engine.begin() as connection:
                connection.execute(text("SELECT set_config('app.workspace_id', :workspace, true)"), {"workspace": self.workspace_a})
                connection.execute(text(
                    "INSERT INTO metric_observations "
                    "(id,workspace_id,post_id,metric,traffic,status,value,window_start,window_end,source_ref,observed_at) "
                    "VALUES (:id,:workspace,:post,'reactions','organic','observed',1,now()-interval '2 days',now()-interval '1 day','forged',now())"
                ), {"id": str(uuid.uuid4()), "workspace": self.workspace_a, "post": post_b})

    def test_weekly_results_follow_workspace_rls(self):
        report_a, report_b = str(uuid.uuid4()), str(uuid.uuid4())
        with self.engine.begin() as connection:
            for workspace, user, report in ((self.workspace_a, self.user_a, report_a), (self.workspace_b, self.user_b, report_b)):
                connection.execute(text("INSERT INTO weekly_reports (id,workspace_id,week_start,revision,report,created_by_user_id,created_at,updated_at) VALUES (:id,:workspace,'2026-09-14',1,'{}',:user,now(),now())"),
                    {"id": report, "workspace": workspace, "user": user})
        with self.app_engine.begin() as connection:
            connection.execute(text("SELECT set_config('app.workspace_id', :workspace, true)"), {"workspace": self.workspace_a})
            self.assertEqual(connection.execute(text("SELECT id FROM weekly_reports")).scalars().all(), [report_a])
        with self.assertRaises(Exception):
            with self.app_engine.begin() as connection:
                connection.execute(text("SELECT set_config('app.workspace_id', :workspace, true)"), {"workspace": self.workspace_a})
                connection.execute(text("INSERT INTO weekly_reports (id,workspace_id,week_start,revision,report,created_by_user_id,created_at,updated_at) VALUES (:id,:workspace,'2026-09-21',1,'{}',:user,now(),now())"),
                    {"id": str(uuid.uuid4()), "workspace": self.workspace_b, "user": self.user_b})

    def test_phase7_weekly_plans_are_workspace_isolated(self):
        plan_a, plan_b = str(uuid.uuid4()), str(uuid.uuid4())
        with self.engine.begin() as connection:
            for plan_id, workspace, user in ((plan_a, self.workspace_a, self.user_a),
                                              (plan_b, self.workspace_b, self.user_b)):
                connection.execute(text(
                    "INSERT INTO weekly_plans "
                    "(id,workspace_id,week_start,revision,status,profile_version,strategy,items,created_by_user_id,created_at) "
                    "VALUES (:id,:workspace,'2026-12-28',1,'draft',1,'{}','[]',:user,now())"
                ), {"id": plan_id, "workspace": workspace, "user": user})
        with self.app_engine.begin() as connection:
            connection.execute(text("SELECT set_config('app.workspace_id', :workspace, true)"),
                               {"workspace": self.workspace_a})
            visible = connection.execute(text("SELECT id FROM weekly_plans")).scalars().all()
        self.assertEqual(visible, [plan_a])
        with self.assertRaises(Exception):
            with self.app_engine.begin() as connection:
                connection.execute(text("SELECT set_config('app.workspace_id', :workspace, true)"),
                                   {"workspace": self.workspace_a})
                connection.execute(text(
                    "INSERT INTO weekly_plans "
                    "(id,workspace_id,week_start,revision,status,profile_version,strategy,items,created_by_user_id,created_at) "
                    "VALUES (:id,:workspace,'2027-01-04',1,'draft',1,'{}','[]',:user,now())"
                ), {"id": str(uuid.uuid4()), "workspace": self.workspace_b, "user": self.user_b})


    def test_branding_and_engagement_rls_and_asset_foreign_keys(self):
        assets = {workspace: str(uuid.uuid4()) for workspace in (self.workspace_a, self.workspace_b)}
        posts = {workspace: str(uuid.uuid4()) for workspace in assets}
        with self.engine.begin() as connection:
            for workspace in assets:
                connection.execute(text("INSERT INTO workspace_assets (id,workspace_id,storage_key,original_name,mime_type,sha256,size,asset_type,status,source,metadata,created_at) VALUES (:id,:workspace,:id,'logo.png','image/png',:hash,100,'image','ready','upload','{}',now())"),
                    {"id": assets[workspace], "workspace": workspace, "hash": uuid.uuid4().hex * 2})
                connection.execute(text("INSERT INTO social_posts (id,workspace_id,provider,account_id,source_id,text,provenance,observed_at) VALUES (:id,:workspace,'instagram','account',:id,'Post','owner_imported',now())"), {"id": posts[workspace], "workspace": workspace})
                connection.execute(text("INSERT INTO branding_setups (workspace_id,answers,logo_asset_id,public_context_confirmed,updated_at) VALUES (:workspace,'{}',:logo,false,now())"), {"workspace": workspace, "logo": assets[workspace]})
                connection.execute(text("INSERT INTO engagement_snapshots (id,workspace_id,post_id,day,counts,source,status,observed_at) VALUES (:id,:workspace,:post,CURRENT_DATE,'{}','fixture','unavailable',now())"),
                    {"id": str(uuid.uuid4()), "workspace": workspace, "post": posts[workspace]})
        with self.app_engine.begin() as connection:
            connection.execute(text("SELECT set_config('app.workspace_id', :workspace, true)"), {"workspace": self.workspace_a})
            for table in ("branding_setups", "engagement_snapshots"):
                self.assertEqual(connection.execute(text(f"SELECT workspace_id FROM {table}")).scalars().all(), [self.workspace_a])
        with self.assertRaises(Exception):
            with self.engine.begin() as connection:
                connection.execute(text("UPDATE branding_setups SET logo_asset_id=:logo WHERE workspace_id=:workspace"),
                    {"logo": assets[self.workspace_b], "workspace": self.workspace_a})
        with self.assertRaises(Exception):
            with self.engine.begin() as connection:
                connection.execute(text("UPDATE engagement_snapshots SET post_id=:post WHERE workspace_id=:workspace"),
                    {"post": posts[self.workspace_b], "workspace": self.workspace_a})


if __name__ == "__main__":
    unittest.main()
