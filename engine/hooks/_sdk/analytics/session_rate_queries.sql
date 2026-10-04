-- Session-normalized skill/hook rates for PostHog HogQL (Data table insights).
-- Use quantileExact(p)(x). Exclude blank/<synthetic> model. Prefer sessions >= 3.
-- Dashboard: Catstack hooks and skills (project 489684 / dashboard 2165552)

-- Skill fires per session by harness
SELECT skill, harness, count() AS sessions, sum(fires) AS total_fires,
  round(avg(fires), 2) AS mean_per_session,
  quantileExact(0.5)(fires) AS p50, quantileExact(0.95)(fires) AS p95, max(fires) AS max_per_session
FROM (
  SELECT toString(properties.skill) AS skill, toString(properties.harness) AS harness,
         toString(properties.session_id) AS session_id, count() AS fires
  FROM events
  WHERE event = 'catstack_hook_event' AND timestamp > now() - INTERVAL 30 DAY
    AND properties.action = 'skill_used' AND notEmpty(toString(properties.skill))
    AND notEmpty(toString(properties.session_id))
    AND coalesce(toString(properties.model), '') NOT IN ('', '<synthetic>')
  GROUP BY skill, harness, session_id
)
GROUP BY skill, harness HAVING sessions >= 3 ORDER BY total_fires DESC LIMIT 50;

-- Skill fires per session by model
SELECT skill, harness, model, count() AS sessions, sum(fires) AS total_fires,
  round(avg(fires), 2) AS mean_per_session,
  quantileExact(0.5)(fires) AS p50, quantileExact(0.95)(fires) AS p95
FROM (
  SELECT toString(properties.skill) AS skill, toString(properties.harness) AS harness,
         toString(properties.model) AS model, toString(properties.session_id) AS session_id, count() AS fires
  FROM events
  WHERE event = 'catstack_hook_event' AND timestamp > now() - INTERVAL 30 DAY
    AND properties.action = 'skill_used' AND notEmpty(toString(properties.skill))
    AND notEmpty(toString(properties.session_id))
    AND coalesce(toString(properties.model), '') NOT IN ('', '<synthetic>')
  GROUP BY skill, harness, model, session_id
)
GROUP BY skill, harness, model HAVING sessions >= 3 ORDER BY total_fires DESC LIMIT 50;

-- Skill breadth per session by harness x model
SELECT harness, model, count() AS sessions,
  round(avg(distinct_skills), 2) AS mean_skills_per_session,
  quantileExact(0.5)(distinct_skills) AS p50_skills, quantileExact(0.95)(distinct_skills) AS p95_skills,
  round(avg(skill_fires), 2) AS mean_fires_per_session,
  quantileExact(0.5)(skill_fires) AS p50_fires, quantileExact(0.95)(skill_fires) AS p95_fires
FROM (
  SELECT toString(properties.harness) AS harness, toString(properties.model) AS model,
         toString(properties.session_id) AS session_id,
         uniqExact(properties.skill) AS distinct_skills, count() AS skill_fires
  FROM events
  WHERE event = 'catstack_hook_event' AND timestamp > now() - INTERVAL 30 DAY
    AND properties.action = 'skill_used' AND notEmpty(toString(properties.skill))
    AND notEmpty(toString(properties.session_id))
    AND coalesce(toString(properties.model), '') NOT IN ('', '<synthetic>')
  GROUP BY harness, model, session_id
)
GROUP BY harness, model ORDER BY sessions DESC LIMIT 30;
