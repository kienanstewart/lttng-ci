import hudson.matrix.*
import hudson.model.*
import jenkins.model.*

import static java.util.Calendar.*

import com.sonyericsson.hudson.plugins.gerrit.trigger.hudsontrigger.GerritCause;
import com.sonymobile.tools.gerrit.gerritevents.dto.attr.Change;

// Iterate over all jobs and find the ones that have a hudson.plugins.git.util.BuildData
// as an action.
//
// We then clean it by removing the useless array action.buildsByBranchName
//
def cleaned_build = 0;
def cleaned_run = 0;
def hoursToKeepSuccessfulBuilds = build.getEnvironment(listener).get('HOURS_TO_KEEP_SUCCESSFUL_BUILDS');
def jobPattern = build.getEnvironment(listener).get('JOB_PATTERN');

if (hoursToKeepSuccessfulBuilds != null && hoursToKeepSuccessfulBuilds.isInteger()) {
  hoursToKeepSuccessfulBuilds = hoursToKeepSuccessfulBuilds as Integer;
} else {
  hoursToKeepSuccessfulBuilds = -1;
}

println("Hours to keep successful builds: ${hoursToKeepSuccessfulBuilds}");
println("Job pattern: ${jobPattern}");
def matchedJobs = Jenkins.instance.items.findAll { job ->
    job.name =~ /$jobPattern/
}

for (job in matchedJobs) {
  println("job: " + job.name);

  def changes = []

  for (build in job.getBuilds()) {
    println("  build: " + build.number);

    // Skip currently building builds
    if (build.isBuilding()) {
      println("  Is building, skip it.");
      continue
    }

    // Keep only the last build of a Gerrit Change
    if (build.getCause(GerritCause.class) != null &&
        build.getCause(GerritCause.class).getEvent() != null &&
        build.getCause(GerritCause.class).getEvent().getChange() != null) {

      Change change = build.getCause(GerritCause.class).getEvent().getChange()

      if (changes.contains(change)) {
        println("  Is not the latest for change " + change.getId());
        if (build.result == "SUCCESS") {
          println("    Result is 'SUCCESS', deleting it");
          build.delete()
          continue
        }
      } else {
        changes.add(change)
      }
    }

    def cutoff = Calendar.instance
    cutoff.add(Calendar.HOUR_OF_DAY, -hoursToKeepSuccessfulBuilds)

    // Delete successful builds
    if (build.result.toString() == 'SUCCESS' && hoursToKeepSuccessfulBuilds >= 0) {
      if (build.getDuration() > Integer.MAX_VALUE) {
        println("  Has a duration > Integer.MAX_VALUE, will not attempt to remove based on age");
      }
      else {
        def endTimestamp = build.getTimestamp();
        endTimestamp.add(Calendar.MILLISECOND, build.getDuration() as Integer);
        if (endTimestamp.before(cutoff)) {
          println("  Is " + build.result.toString() + " and older than " + hoursToKeepSuccessfulBuilds + " hours, DELETE it.");
          build.delete()
          continue
        } else {
          println("  Is " + build.result.toString() + " but newer than " + hoursToKeepSuccessfulBuilds + " hours.");
        }
      }
    }

    // It is possible for a build to have multiple BuildData actions
    // since we can use the Mulitple SCM plugin.
    def buildModified = false;
    def gitActions = build.getActions(hudson.plugins.git.util.BuildData.class)
    if (gitActions != null) {
      for (action in gitActions) {
        if (action.buildsByBranchName.size() < 2) {
          continue;
        }

        action.buildsByBranchName = new HashMap<String, Build>();
        hudson.plugins.git.Revision r = action.getLastBuiltRevision();
        if (r != null) {
          for (branch in r.getBranches()) {
            action.buildsByBranchName.put(branch.getName(), action.lastBuild)
          }
        }
        build.actions.remove(action);
        build.actions.add(action);
        build_modified = true;
      }
    }

    if (buildModified) {
      build.save();
      cleaned_build += 1;
    }

    if (job instanceof MatrixProject) {
      for (run in build.getRuns()) {
        println("    run: " + run);

        runModified = false;
        gitActions = run.getActions(hudson.plugins.git.util.BuildData.class)
        if (gitActions != null) {
          for (action in gitActions) {
            if (action.buildsByBranchName.size() < 2) {
              continue;
            }

            action.buildsByBranchName = new HashMap<String, Build>();
            hudson.plugins.git.Revision r = action.getLastBuiltRevision();
            if (r != null) {
              for (branch in r.getBranches()) {
                action.buildsByBranchName.put(branch.getName(), action.lastBuild)
              }
            }
            run.actions.remove(action);
            run.actions.add(action);
            runModified = true;
          }
        }

        if (runModified) {
          run.save();
          cleaned_run += 1;
        }
      }
    }
  }
}

println("Cleaned git action buildsByBranchName for ${cleaned_build} builds, ${cleaned_run} runs");
