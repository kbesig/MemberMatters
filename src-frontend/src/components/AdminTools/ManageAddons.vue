<template>
  <div class="q-pa-md">
    <div class="text-h4 q-mb-md">{{ $t('menuLink.addons') }}</div>

    <q-tabs
      v-model="activeTab"
      dense
      class="text-grey"
      active-color="primary"
      indicator-color="primary"
      align="justify"
      narrow-indicator
    >
      <q-tab
        name="additional-members"
        :label="$t('adminTools.addons.additionalMembersTab')"
      />
      <!-- Future tabs can be added here -->
    </q-tabs>

    <q-separator />

    <q-tab-panels v-model="activeTab" animated>
      <q-tab-panel name="additional-members">
        <div class="row q-gutter-md">
          <q-card class="full-width">
            <q-card-section class="row items-center">
              <span class="q-ml-sm">{{
                $t('adminTools.addons.additionalMembersCost')
              }}</span>
            </q-card-section>

            <q-card-section>
              <div class="row items-center q-gutter-md q-mb-md">
                <q-select
                  v-model="selectedAddon"
                  :options="addonOptions"
                  :label="$t('adminTools.addons.currentAdditionalMemberCost')"
                  outlined
                  dense
                  emit-value
                  map-options
                  option-value="id"
                  option-label="display_name"
                  clearable
                  style="min-width: 300px"
                  :loading="savingSelection"
                  @update:model-value="updateCurrentAddon"
                />
                <q-chip
                  v-if="selectedAddon"
                  :label="$t('adminTools.addons.currentlySelected')"
                  color="primary"
                  text-color="white"
                />
              </div>
            </q-card-section>

            <q-card-section class="row items-center q-pt-none">
              <q-table
                flat
                @row-click="manageAddon"
                :rows="addons"
                :columns="[
                  {
                    name: 'name',
                    label: 'Name',
                    field: 'name',
                    sortable: true,
                  },
                  {
                    name: 'description',
                    label: 'Description',
                    field: 'description',
                    sortable: true,
                  },
                  {
                    name: 'visible',
                    label: 'Visible',
                    field: 'visible',
                    sortable: true,
                  },
                  {
                    name: 'cost',
                    label: 'Cost',
                    field: 'cost',
                    sortable: true,
                    format: (val) => `$${(val / 100).toFixed(2)}`,
                  },
                  {
                    name: 'interval',
                    label: 'Interval',
                    field: 'interval',
                    sortable: true,
                    format: (val, row) =>
                      `${row.interval_count} ${row.interval}${
                        row.interval_count > 1 ? 's' : ''
                      }`,
                  },
                  {
                    name: 'stripe_synced',
                    label: 'Stripe Synced',
                    field: 'stripe_synced',
                    sortable: true,
                  },
                ]"
                row-key="id"
                :filter="filter"
                v-model:pagination="pagination"
                :grid="$q.screen.xs"
                :no-data-label="$t('adminTools.addons.noadditionalMembersCost')"
                :loading="loading"
              >
                <template v-slot:top-right>
                  <q-input
                    v-model="filter"
                    outlined
                    dense
                    debounce="300"
                    placeholder="Search"
                  >
                    <template v-slot:append>
                      <q-icon :name="icons.search" />
                    </template>
                  </q-input>
                </template>
                <template v-slot:top-left>
                  <q-btn
                    @click="addAddonDialog = true"
                    round
                    color="primary"
                    :icon="icons.addAlternative"
                  >
                    <q-tooltip :delay="500">{{
                      $t('adminTools.addons.addAdditionalMemberCost')
                    }}</q-tooltip>
                  </q-btn>
                </template>
                <template v-slot:body-cell-visible="props">
                  <q-td :props="props">
                    <q-chip
                      :color="props.value ? 'positive' : 'negative'"
                      text-color="white"
                      dense
                    >
                      {{ props.value ? 'Yes' : 'No' }}
                    </q-chip>
                  </q-td>
                </template>
                <template v-slot:body-cell-stripe_synced="props">
                  <q-td :props="props">
                    <q-chip
                      :color="props.value ? 'positive' : 'warning'"
                      text-color="white"
                      dense
                    >
                      {{ props.value ? 'Synced' : 'Not Synced' }}
                    </q-chip>
                  </q-td>
                </template>
              </q-table>
            </q-card-section>
          </q-card>

          <!-- Add Addon Dialog -->
          <q-dialog v-model="addAddonDialog" persistent>
            <q-card style="min-width: 400px">
              <q-card-section class="row items-center">
                <span class="q-ml-sm">{{
                  $t('adminTools.addons.addAdditionalMemberCost')
                }}</span>
              </q-card-section>

              <q-card-actions align="right">
                <q-form ref="formRef" @submit="submitAddonForm()">
                  <div class="row q-col-gutter-sm">
                    <q-input
                      class="col-sm-6 col-xs-12"
                      v-model="addonForm.name"
                      outlined
                      :debounce="debounceLength"
                      :label="$t('form.name')"
                      :rules="[
                        (val) =>
                          validateNotEmpty(val) ||
                          $t('validation.cannotBeEmpty'),
                      ]"
                      :disable="addonForm.success"
                    />
                    <q-input
                      class="col-sm-6 col-xs-12"
                      v-model="addonForm.description"
                      outlined
                      :debounce="debounceLength"
                      :label="$t('form.description')"
                      :disable="addonForm.success"
                    />
                    <q-input
                      class="col-sm-6 col-xs-12"
                      v-model="addonForm.currency"
                      outlined
                      :debounce="debounceLength"
                      :label="$t('form.currency')"
                      :rules="[
                        (val) =>
                          validateNotEmpty(val) ||
                          $t('validation.cannotBeEmpty'),
                      ]"
                      :disable="addonForm.success"
                    />
                    <q-input
                      class="col-sm-6 col-xs-12"
                      v-model="addonForm.costString"
                      outlined
                      :debounce="debounceLength"
                      :label="$t('form.cost')"
                      :rules="[
                        (val) =>
                          validateNotEmpty(val) ||
                          $t('validation.cannotBeEmpty'),
                      ]"
                      :disable="addonForm.success"
                      prefix="$"
                    />

                    <q-checkbox
                      class="col-sm-6 col-xs-12"
                      v-model="addonForm.visible"
                      :label="$t('form.visibleToMembers')"
                    />

                    <q-card-section class="col-12">
                      <span class="q-ml-sm">{{
                        $t('adminTools.addons.recurringDescription')
                      }}</span>
                    </q-card-section>

                    <q-input
                      class="col-sm-6 col-xs-12"
                      v-model="addonForm.interval_count"
                      outlined
                      :debounce="debounceLength"
                      :label="$t('form.intervalCount')"
                      :rules="[
                        (val) =>
                          validateNotEmpty(val) ||
                          $t('validation.cannotBeEmpty'),
                      ]"
                      :disable="addonForm.success"
                      type="number"
                    />
                    <q-select
                      outlined
                      class="col-sm-6 col-xs-12"
                      v-model="addonForm.interval"
                      :debounce="debounceLength"
                      :label="$t('form.interval')"
                      :rules="[
                        (val) =>
                          validateNotEmpty(val) ||
                          $t('validation.cannotBeEmpty'),
                      ]"
                      :disable="addonForm.success"
                      :options="intervalOptions"
                      emit-value
                      options-dense
                      map-options
                    />

                    <q-input
                      class="col-sm-6 col-xs-12"
                      v-model="addonForm.min_quantity"
                      outlined
                      :debounce="debounceLength"
                      :label="$t('adminTools.addons.minQuantity')"
                      :rules="[
                        (val) =>
                          validateNotEmpty(val) ||
                          $t('validation.cannotBeEmpty'),
                      ]"
                      :disable="addonForm.success"
                      type="number"
                    />
                    <q-input
                      class="col-sm-6 col-xs-12"
                      v-model="addonForm.max_quantity"
                      outlined
                      :debounce="debounceLength"
                      :label="$t('adminTools.addons.maxQuantity')"
                      :rules="[
                        (val) =>
                          validateNotEmpty(val) ||
                          $t('validation.cannotBeEmpty'),
                      ]"
                      :disable="addonForm.success"
                      type="number"
                    />
                  </div>

                  <q-banner
                    v-if="addonForm.success"
                    class="bg-positive text-white q-my-md"
                  >
                    {{ $t('adminTools.addons.additionalMemberCostCreated') }}
                  </q-banner>

                  <q-banner
                    v-if="addonForm.error"
                    class="bg-negative text-white q-my-md"
                  >
                    {{ $t('adminTools.addons.additionalMemberCostFailed') }}
                  </q-banner>

                  <q-card-actions
                    v-if="!addonForm.success"
                    class="text-primary"
                  >
                    <q-space />
                    <q-btn
                      v-close-popup
                      flat
                      :label="$t('button.cancel')"
                      :disable="addonForm.loading"
                    />
                    <q-btn
                      color="primary"
                      :label="$t('button.submit')"
                      :loading="addonForm.loading"
                      :disable="addonForm.loading"
                      type="submit"
                    />
                  </q-card-actions>

                  <q-card-actions v-else align="right" class="text-primary">
                    <q-btn
                      v-close-popup
                      flat
                      :label="$t('button.close')"
                      @click="resetAddonForm"
                    />
                  </q-card-actions>
                </q-form>
              </q-card-actions>
            </q-card>
          </q-dialog>
        </div>
      </q-tab-panel>
    </q-tab-panels>
  </div>
</template>

<script lang="ts">
import { defineComponent } from 'vue';
import { AxiosResponse } from 'axios';
import { api } from 'boot/axios';
import icons from '../../icons';
import formatMixin from '../../mixins/formatMixin';
import formMixin from '../../mixins/formMixin';

export default defineComponent({
  name: 'ManageAddons',
  mixins: [formatMixin, formMixin],
  data() {
    return {
      activeTab: 'additional-members',
      addons: [],
      loading: false,
      selectedAddon: null as number | null,
      savingSelection: false,
      addonForm: {
        loading: false,
        error: false,
        success: false,
        name: '',
        description: '',
        addon_type: 'additional_member',
        visible: true,
        currency: 'aud',
        costString: '',
        cost: 0,
        interval_count: 1,
        interval: 'month',
        min_quantity: 1,
        max_quantity: 10,
      },
      addAddonDialog: false,
      filter: '',
      pagination: {
        sortBy: 'name',
        descending: false,
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        rowsPerPage: (this as any).$q.screen.xs ? 3 : 10,
      },
      intervalOptions: [
        { label: 'Day', value: 'day' },
        { label: 'Week', value: 'week' },
        { label: 'Month', value: 'month' },
      ],
    };
  },
  mounted() {
    this.getAddons();
    this.getCurrentAddon();
  },
  computed: {
    icons() {
      return icons;
    },
    addonOptions() {
      return this.addons.map((addon: any) => ({
        id: addon.id,
        display_name: `${addon.name} - $${(addon.cost / 100).toFixed(2)}/${
          addon.interval_count
        } ${addon.interval}${addon.interval_count > 1 ? 's' : ''}`,
        ...addon,
      }));
    },
  },
  methods: {
    async getAddons() {
      this.loading = true;
      try {
        const response: AxiosResponse = await api.get('/api/admin/addons/', {
          params: { addon_type: 'additional_member' },
        });
        this.addons = response.data;
      } catch (error) {
        this.$q.dialog({
          title: this.$tc('error.error'),
          message: this.$tc('error.requestFailed'),
        });
      } finally {
        this.loading = false;
      }
    },
    async submitAddonForm() {
      this.addonForm.loading = true;
      this.addonForm.error = false;
      this.addonForm.success = false;
      this.addonForm.cost = parseFloat(this.addonForm.costString) * 100;

      try {
        await api.post('/api/admin/addons/', this.addonForm);
        this.getAddons();
        this.addonForm.success = true;
        this.addonForm.error = false;
      } catch (error) {
        this.addonForm.success = false;
        this.addonForm.error = true;
      } finally {
        this.addonForm.loading = false;
      }
    },
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    manageAddon(evt: InputEvent, row: any) {
      // TODO: implement addon editing
      console.log('Managing addon:', row);
    },
    resetAddonForm() {
      this.addonForm = {
        loading: false,
        error: false,
        success: false,
        name: '',
        description: '',
        addon_type: 'additional_member',
        visible: true,
        currency: 'aud',
        costString: '',
        cost: 0,
        interval_count: 1,
        interval: 'month',
        min_quantity: 1,
        max_quantity: 10,
      };
      this.addAddonDialog = false;
    },
    async getCurrentAddon() {
      try {
        const response: AxiosResponse = await api.get(
          '/api/admin/addons/current-additional-member/'
        );
        if (response.data.success && response.data.addon_id) {
          this.selectedAddon = response.data.addon_id;
        }
      } catch (error) {
        // Setting might not exist yet, which is fine
        console.log('No current additional member addon set');
      }
    },
    async updateCurrentAddon(addonId: number | null) {
      this.savingSelection = true;
      try {
        const response: AxiosResponse = await api.post(
          '/api/admin/addons/current-additional-member/',
          {
            addon_id: addonId,
          }
        );

        if (response.data.success) {
          this.$q.notify({
            type: 'positive',
            message: this.$tc(
              'adminTools.addons.currentAdditionalMemberCostUpdated'
            ),
          });
        } else {
          this.$q.notify({
            type: 'negative',
            message: this.$tc('error.requestFailed'),
          });
        }
      } catch (error) {
        this.$q.notify({
          type: 'negative',
          message: this.$tc('error.requestFailed'),
        });
      } finally {
        this.savingSelection = false;
      }
    },
  },
});
</script>
