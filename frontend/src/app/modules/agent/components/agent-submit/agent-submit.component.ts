import { Component } from '@angular/core';
import { FormBuilder, Validators } from '@angular/forms';
import { Router } from '@angular/router';
import { AgentService } from 'src/app/services/agent.service';

@Component({
  selector: 'app-agent-submit',
  templateUrl: './agent-submit.component.html',
  styleUrls: ['./agent-submit.component.scss']
})
export class AgentSubmitComponent {
  errorMessage = '';
  isSubmitting = false;

  form = this.fb.group({
    prompt: ['', [Validators.required, Validators.maxLength(10000)]],
    urls: [''],
    schema: [''],
    strictConstrainToURLs: [false],
    model: ['spark-1-mini'],
    maxCredits: [2500, [Validators.required, Validators.min(1)]]
  });

  constructor(
    private fb: FormBuilder,
    private agentService: AgentService,
    private router: Router
  ) { }

  submit(): void {
    this.errorMessage = '';
    if (this.form.invalid) {
      this.errorMessage = 'Please fill in the required fields.';
      return;
    }

    const prompt = this.form.value.prompt || '';
    const urlText = this.form.value.urls || '';
    const schemaText = this.form.value.schema || '';

    const urls = urlText
      .split(/[\n,]/)
      .map(item => item.trim())
      .filter(Boolean);

    let schema: any = undefined;
    if (schemaText.trim()) {
      try {
        schema = JSON.parse(schemaText);
      } catch (error) {
        this.errorMessage = 'Schema must be valid JSON.';
        return;
      }
    }

    const payload = {
      prompt,
      urls: urls.length ? urls : undefined,
      schema,
      strictConstrainToURLs: this.form.value.strictConstrainToURLs || false,
      model: this.form.value.model || undefined,
      maxCredits: this.form.value.maxCredits || 2500
    };

    this.isSubmitting = true;
    this.agentService.startJob(payload).subscribe({
      next: (response) => {
        this.isSubmitting = false;
        this.agentService.setJobId(response.id, payload.maxCredits);
        this.agentService.startPolling(response.id);
        this.router.navigate(['main', 'agent', 'status']);
      },
      error: (err) => {
        this.isSubmitting = false;
        this.errorMessage = err?.error?.detail || 'Failed to start agent job.';
      }
    });
  }
}
